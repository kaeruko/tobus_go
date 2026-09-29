#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import uuid
from io import BytesIO
from pathlib import Path

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError


REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.services.explore_editorial_content import (  # noqa: E402
    ALLOWED_IMAGE_SUFFIXES,
    ExploreContentError,
    build_stop_route_catalog,
    compile_csv,
    master_data_dir,
    read_authoring_groups,
    source_paths,
    validate_image_name,
    write_authoring_groups,
)


CITY = "tokyo"
CSV_PATH, IMAGES_DIR = source_paths(CITY)
DATA_DIR = master_data_dir(CITY)
PUBLISH_SCRIPT = REPO_ROOT / "scripts" / "publish_explore_content.py"


@st.cache_data(show_spinner=False)
def load_catalog() -> list[dict]:
    return build_stop_route_catalog(DATA_DIR)


def load_groups() -> list[dict]:
    return read_authoring_groups(CSV_PATH, IMAGES_DIR)


def find_group_index(
    groups: list[dict],
    *,
    stop_name: str,
    route_id: str,
) -> int | None:
    for index, group in enumerate(groups):
        if group["stop_name"] == stop_name and group["route_id"] == route_id:
            return index
    return None


IMAGE_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}
ACCEPTED_SOURCE_FORMATS_BY_SUFFIX = {
    ".jpg": frozenset({"JPEG", "MPO"}),
    ".jpeg": frozenset({"JPEG", "MPO"}),
    ".png": frozenset({"PNG"}),
    ".webp": frozenset({"WEBP"}),
}
EXIF_ORIENTATION_TAG = 274
VALID_EXIF_ORIENTATIONS = frozenset(range(1, 9))


def normalize_uploaded_image(content: bytes, *, suffix: str) -> bytes:
    expected_format = IMAGE_FORMAT_BY_SUFFIX.get(suffix)
    if expected_format is None:
        raise ExploreContentError(
            f"unsupported uploaded image extension {suffix!r}"
        )

    accepted_source_formats = ACCEPTED_SOURCE_FORMATS_BY_SUFFIX[suffix]

    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            detected_format = image.format
            if detected_format not in accepted_source_formats:
                raise ExploreContentError(
                    "uploaded image format does not match its extension: "
                    f"extension={suffix!r}, detected_format={detected_format!r}"
                )

            orientation = image.getexif().get(EXIF_ORIENTATION_TAG, 1)
            if orientation not in VALID_EXIF_ORIENTATIONS:
                raise ExploreContentError(
                    f"invalid EXIF orientation value: {orientation!r}"
                )

            needs_transcode = detected_format != expected_format
            if orientation == 1 and not needs_transcode:
                return content

            normalized = ImageOps.exif_transpose(image)
            output = BytesIO()
            save_kwargs = {}
            icc_profile = image.info.get("icc_profile")
            if icc_profile is not None:
                save_kwargs["icc_profile"] = icc_profile
            normalized.save(output, format=expected_format, **save_kwargs)
            return output.getvalue()
    except UnidentifiedImageError as error:
        raise ExploreContentError(
            "uploaded file could not be decoded as an image"
        ) from error
    except OSError as error:
        raise ExploreContentError(
            f"failed to decode or normalize uploaded image: {error}"
        ) from error


def save_group(
    *,
    stop_name: str,
    route_id: str,
    comment: str,
    comment_en: str,
    uploaded_file,
    caption: str,
    caption_en: str,
) -> str | None:
    groups = load_groups()
    group_index = find_group_index(
        groups,
        stop_name=stop_name,
        route_id=route_id,
    )

    new_filename: str | None = None
    new_image_path: Path | None = None

    if uploaded_file is not None:
        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
            raise ExploreContentError(
                f"unsupported uploaded image extension {suffix!r}; "
                f"expected one of: {allowed}"
            )
        content = uploaded_file.getvalue()
        if not content:
            raise ExploreContentError("uploaded image is empty")
        content = normalize_uploaded_image(content, suffix=suffix)

        new_filename = validate_image_name(
            f"explore_{uuid.uuid4().hex}{suffix}"
        )
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        new_image_path = IMAGES_DIR / new_filename
        if new_image_path.exists():
            raise ExploreContentError(
                f"generated image path already exists: {new_image_path}"
            )
        new_image_path.write_bytes(content)

    try:
        if group_index is None:
            images = []
            if new_filename is not None:
                images.append(
                    {
                        "file": new_filename,
                        "caption": caption,
                        "caption_en": caption_en,
                    }
                )
            if not comment and not images:
                raise ExploreContentError(
                    "comment or image is required for a new entry"
                )
            groups.append(
                {
                    "stop_name": stop_name,
                    "route_id": route_id,
                    "comment": comment,
                    "comment_en": comment_en,
                    "images": images,
                }
            )
        else:
            group = {
                "stop_name": groups[group_index]["stop_name"],
                "route_id": groups[group_index]["route_id"],
                "comment": comment,
                "comment_en": comment_en,
                "images": [
                    dict(image) for image in groups[group_index]["images"]
                ],
            }
            if new_filename is not None:
                group["images"].append(
                    {
                        "file": new_filename,
                        "caption": caption,
                        "caption_en": caption_en,
                    }
                )
            if not group["comment"] and not group["images"]:
                raise ExploreContentError(
                    "comment or image is required for an entry"
                )
            groups[group_index] = group

        temp_csv = CSV_PATH.parent / f".spots.{uuid.uuid4().hex}.tmp.csv"
        try:
            write_authoring_groups(temp_csv, groups)
            compile_csv(
                temp_csv,
                IMAGES_DIR,
                data_dir=DATA_DIR,
            )
            temp_csv.replace(CSV_PATH)
        finally:
            if temp_csv.exists():
                temp_csv.unlink()

    except Exception:
        if new_image_path is not None and new_image_path.exists():
            new_image_path.unlink()
        raise

    return new_filename



def delete_group_image(
    *,
    stop_name: str,
    route_id: str,
    filename: str,
) -> None:
    filename = validate_image_name(filename)
    groups = load_groups()
    group_index = find_group_index(
        groups,
        stop_name=stop_name,
        route_id=route_id,
    )
    if group_index is None:
        raise ExploreContentError(
            "entry was not found for image deletion: "
            f"stop_name={stop_name!r}, route_id={route_id!r}"
        )

    group = groups[group_index]
    matching_indexes = [
        index
        for index, image in enumerate(group["images"])
        if image["file"] == filename
    ]
    if len(matching_indexes) != 1:
        raise ExploreContentError(
            "image reference count must be exactly 1 before deletion: "
            f"filename={filename!r}, count={len(matching_indexes)}"
        )

    image_path = IMAGES_DIR / filename
    if not image_path.is_file():
        raise ExploreContentError(
            f"image file was not found for deletion: {image_path}"
        )
    image_content = image_path.read_bytes()

    updated_group = {
        "stop_name": group["stop_name"],
        "route_id": group["route_id"],
        "comment": group["comment"],
        "comment_en": group["comment_en"],
        "images": [
            dict(image)
            for index, image in enumerate(group["images"])
            if index != matching_indexes[0]
        ],
    }
    if updated_group["comment"] or updated_group["images"]:
        groups[group_index] = updated_group
    else:
        groups.pop(group_index)

    temp_csv = CSV_PATH.parent / f".spots.{uuid.uuid4().hex}.tmp.csv"
    image_removed = False
    try:
        image_path.unlink()
        image_removed = True
        write_authoring_groups(temp_csv, groups)
        compile_csv(
            temp_csv,
            IMAGES_DIR,
            data_dir=DATA_DIR,
        )
        temp_csv.replace(CSV_PATH)
    except Exception as error:
        if image_removed:
            try:
                image_path.write_bytes(image_content)
            except Exception as restore_error:
                raise ExploreContentError(
                    "image deletion failed and rollback also failed: "
                    f"filename={filename!r}, "
                    f"original_error={error!r}, "
                    f"restore_error={restore_error!r}"
                ) from error
        raise
    finally:
        if temp_csv.exists():
            temp_csv.unlink()

def publish() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PUBLISH_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def main() -> None:
    st.set_page_config(page_title="みつける CMS", page_icon="🚌", layout="wide")
    st.title("みつける CMS")
    st.caption(
        "停留所名 + 系統で対象を決めます。odpt:note は参照しません。"
        "同じ名前・同じ系統の上り/下りはまとめて扱います。"
    )

    try:
        catalog = load_catalog()
        groups = load_groups()
    except ExploreContentError as error:
        st.error(str(error))
        st.stop()

    query = st.text_input(
        "停留所名を検索",
        placeholder="例: 押上",
    ).strip()

    if not query:
        st.info("停留所名の一部を入力してください。")
    else:
        matched_stops = [
            item for item in catalog if query in item["stop_name"]
        ]
        if not matched_stops:
            st.warning("該当する停留所がありません。")
        else:
            stop_names = [item["stop_name"] for item in matched_stops]
            selected_stop_name = st.selectbox(
                "停留所",
                stop_names,
            )
            selected_stop = next(
                item
                for item in matched_stops
                if item["stop_name"] == selected_stop_name
            )

            routes = selected_stop["routes"]
            route_by_id = {
                route["route_id"]: route
                for route in routes
            }
            selected_route_id = st.selectbox(
                "系統",
                [route["route_id"] for route in routes],
                format_func=lambda route_id: (
                    f"{route_by_id[route_id]['route_label']} "
                    f"（対象乗り場 {len(route_by_id[route_id]['pole_ids'])}件）"
                ),
            )
            selected_route = route_by_id[selected_route_id]

            st.write(
                f"**{selected_stop_name} / "
                f"{selected_route['route_label']}**"
            )
            st.caption(
                f"この組み合わせに一致するBusstopPole "
                f"{len(selected_route['pole_ids'])}件を同じ掲載内容にします。"
            )
            with st.expander("内部のBusstopPole IDを確認"):
                st.code("\n".join(selected_route["pole_ids"]))

            existing_index = find_group_index(
                groups,
                stop_name=selected_stop_name,
                route_id=selected_route_id,
            )
            existing = (
                groups[existing_index]
                if existing_index is not None
                else None
            )

            widget_scope = f"{selected_stop_name}::{selected_route_id}"
            comment = st.text_area(
                "コメント（日本語）",
                value=existing["comment"] if existing else "",
                height=120,
                key=f"comment::{widget_scope}",
            )
            comment_en = st.text_area(
                "コメント（英語・任意）",
                value=existing["comment_en"] if existing else "",
                height=120,
                key=f"comment_en::{widget_scope}",
            )

            if existing and existing["images"]:
                st.subheader("登録済みの写真")
                for image in existing["images"]:
                    image_path = IMAGES_DIR / image["file"]
                    st.image(
                        str(image_path),
                        caption=image["caption"] or image["file"],
                        width=320,
                    )
                    if st.button(
                        "この写真を削除",
                        key=f"delete::{widget_scope}::{image['file']}",
                    ):
                        try:
                            delete_group_image(
                                stop_name=selected_stop_name,
                                route_id=selected_route_id,
                                filename=image["file"],
                            )
                        except ExploreContentError as error:
                            st.error(str(error))
                        except Exception as error:
                            st.exception(error)
                        else:
                            st.success("写真を削除しました。")
                            st.rerun()

            uploaded = st.file_uploader(
                "写真を追加",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=False,
                key=f"upload::{widget_scope}",
            )
            caption = st.text_input(
                "追加する写真のキャプション（日本語）",
                disabled=uploaded is None,
                key=f"caption::{widget_scope}",
            )
            caption_en = st.text_input(
                "追加する写真のキャプション（英語・任意）",
                disabled=uploaded is None,
                key=f"caption_en::{widget_scope}",
            )

            if st.button("CSVに保存", key=f"save::{widget_scope}"):
                try:
                    filename = save_group(
                        stop_name=selected_stop_name,
                        route_id=selected_route_id,
                        comment=comment,
                        comment_en=comment_en,
                        uploaded_file=uploaded,
                        caption=caption,
                        caption_en=caption_en,
                    )
                except ExploreContentError as error:
                    st.error(str(error))
                except Exception as error:
                    st.exception(error)
                else:
                    if filename is None:
                        st.success("コメントを保存しました。")
                    else:
                        st.success(
                            f"コメントと写真を保存しました: {filename}"
                        )

    st.divider()
    st.subheader("登録済み")
    if groups:
        route_labels = {
            route["route_id"]: route["route_label"]
            for stop in catalog
            for route in stop["routes"]
        }
        table = [
            {
                "停留所": group["stop_name"],
                "系統": route_labels.get(group["route_id"], group["route_id"]),
                "コメント": group["comment"],
                "英語コメント": group["comment_en"],
                "写真数": len(group["images"]),
            }
            for group in groups
        ]
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.caption("まだ登録はありません。")

    st.divider()
    st.subheader("公開")
    st.caption(
        "保存だけではS3は変わりません。公開するときだけこのボタンを押します。"
    )
    if st.button("S3へ公開", type="primary"):
        with st.spinner("公開中..."):
            try:
                result = publish()
            except Exception as error:
                st.exception(error)
            else:
                if result.returncode == 0:
                    st.success("公開しました。")
                    if result.stdout.strip():
                        st.code(result.stdout)
                else:
                    st.error(
                        f"公開に失敗しました。exit code={result.returncode}"
                    )
                    output = "\n".join(
                        part
                        for part in (
                            result.stdout.strip(),
                            result.stderr.strip(),
                        )
                        if part
                    )
                    if output:
                        st.code(output)


if __name__ == "__main__":
    main()
