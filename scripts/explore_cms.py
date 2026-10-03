#!/usr/bin/env python3
from __future__ import annotations

import hashlib
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
    uploaded_files: list,
    captions: list[str],
    captions_en: list[str],
    existing_captions: dict[str, str],
    existing_captions_en: dict[str, str],
) -> list[str]:
    if len(uploaded_files) != len(captions):
        raise ExploreContentError(
            "uploaded_files and captions must have the same length: "
            f"{len(uploaded_files)} != {len(captions)}"
        )
    if len(uploaded_files) != len(captions_en):
        raise ExploreContentError(
            "uploaded_files and captions_en must have the same length: "
            f"{len(uploaded_files)} != {len(captions_en)}"
        )

    groups = load_groups()
    group_index = find_group_index(
        groups,
        stop_name=stop_name,
        route_id=route_id,
    )

    updated_existing_images: list[dict] = []
    if group_index is None:
        if existing_captions or existing_captions_en:
            raise ExploreContentError(
                "existing image captions were provided for a new entry"
            )
    else:
        existing_images = groups[group_index]["images"]
        existing_filenames = [
            validate_image_name(image["file"])
            for image in existing_images
        ]
        if len(set(existing_filenames)) != len(existing_filenames):
            raise ExploreContentError(
                "existing entry contains duplicate image filenames"
            )

        expected_filenames = set(existing_filenames)
        caption_filenames = set(existing_captions)
        caption_en_filenames = set(existing_captions_en)
        if caption_filenames != expected_filenames:
            raise ExploreContentError(
                "existing Japanese caption fields do not match stored images: "
                f"expected={sorted(expected_filenames)!r}, "
                f"received={sorted(caption_filenames)!r}"
            )
        if caption_en_filenames != expected_filenames:
            raise ExploreContentError(
                "existing English caption fields do not match stored images: "
                f"expected={sorted(expected_filenames)!r}, "
                f"received={sorted(caption_en_filenames)!r}"
            )

        updated_existing_images = [
            {
                "file": filename,
                "caption": existing_captions[filename],
                "caption_en": existing_captions_en[filename],
            }
            for filename in existing_filenames
        ]

    prepared_images: list[dict] = []
    image_hashes = {
        hashlib.sha256((IMAGES_DIR / image["file"]).read_bytes()).digest()
        for image in updated_existing_images
    }
    generated_filenames: set[str] = set()
    for index, uploaded_file in enumerate(uploaded_files):
        suffix = Path(uploaded_file.name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
            raise ExploreContentError(
                f"unsupported uploaded image extension {suffix!r}; "
                f"expected one of: {allowed}"
            )

        content = uploaded_file.getvalue()
        if not content:
            raise ExploreContentError(
                f"uploaded image is empty: index={index}, name={uploaded_file.name!r}"
            )
        content = normalize_uploaded_image(content, suffix=suffix)
        content_hash = hashlib.sha256(content).digest()
        if content_hash in image_hashes:
            continue
        image_hashes.add(content_hash)

        filename = validate_image_name(
            f"explore_{uuid.uuid4().hex}{suffix}"
        )
        if filename in generated_filenames:
            raise ExploreContentError(
                f"generated duplicate image name in one save: {filename}"
            )
        image_path = IMAGES_DIR / filename
        if image_path.exists():
            raise ExploreContentError(
                f"generated image path already exists: {image_path}"
            )
        generated_filenames.add(filename)
        prepared_images.append(
            {
                "file": filename,
                "caption": captions[index],
                "caption_en": captions_en[index],
                "content": content,
            }
        )

    new_image_paths: list[Path] = []
    try:
        if prepared_images:
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            for image in prepared_images:
                image_path = IMAGES_DIR / image["file"]
                image_path.write_bytes(image["content"])
                new_image_paths.append(image_path)

        new_image_rows = [
            {
                "file": image["file"],
                "caption": image["caption"],
                "caption_en": image["caption_en"],
            }
            for image in prepared_images
        ]

        if group_index is None:
            if not comment and not new_image_rows:
                raise ExploreContentError(
                    "comment or image is required for a new entry"
                )
            groups.append(
                {
                    "stop_name": stop_name,
                    "route_id": route_id,
                    "comment": comment,
                    "comment_en": comment_en,
                    "images": new_image_rows,
                }
            )
        else:
            group = {
                "stop_name": groups[group_index]["stop_name"],
                "route_id": groups[group_index]["route_id"],
                "comment": comment,
                "comment_en": comment_en,
                "images": updated_existing_images,
            }
            group["images"].extend(new_image_rows)
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
        rollback_errors: list[str] = []
        for image_path in reversed(new_image_paths):
            if not image_path.exists():
                continue
            try:
                image_path.unlink()
            except OSError as error:
                rollback_errors.append(f"{image_path}: {error}")
        if rollback_errors:
            raise ExploreContentError(
                "save failed and image rollback also failed: "
                + " | ".join(rollback_errors)
            )
        raise

    return [image["file"] for image in prepared_images]



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
    if notice := st.session_state.pop("explore_cms_save_notice", None):
        st.success(notice)
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

    route_labels = {
        route["route_id"]: route["route_label"]
        for stop in catalog
        for route in stop["routes"]
    }

    st.subheader("登録済み")
    if groups:
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

        edit_index = st.selectbox(
            "編集する登録済み項目",
            options=list(range(len(groups))),
            format_func=lambda index: (
                f"{groups[index]['stop_name']} / "
                f"{route_labels.get(groups[index]['route_id'], groups[index]['route_id'])}"
            ),
            key="existing_entry_to_edit",
        )
        if st.button("この内容を編集", key="open_existing_entry"):
            edit_group = groups[edit_index]
            st.session_state["explore_cms_query"] = edit_group["stop_name"]
            st.session_state["explore_cms_target_stop"] = edit_group["stop_name"]
            st.session_state["explore_cms_target_route"] = edit_group["route_id"]
            st.rerun()
    else:
        st.caption("まだ登録はありません。")

    st.divider()
    st.subheader("新規・編集")

    query = st.text_input(
        "停留所名を検索",
        placeholder="例: 押上",
        key="explore_cms_query",
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
            target_stop_name = st.session_state.get("explore_cms_target_stop")
            target_route_id = st.session_state.get("explore_cms_target_route")
            stop_index = (
                stop_names.index(target_stop_name)
                if target_stop_name in stop_names
                else 0
            )
            selected_stop_name = st.selectbox(
                "停留所",
                stop_names,
                index=stop_index,
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
            route_ids = [route["route_id"] for route in routes]
            route_index = (
                route_ids.index(target_route_id)
                if selected_stop_name == target_stop_name
                and target_route_id in route_ids
                else 0
            )
            selected_route_id = st.selectbox(
                "系統",
                route_ids,
                index=route_index,
                format_func=lambda route_id: (
                    f"{route_by_id[route_id]['route_label']} "
                    f"（対象乗り場 {len(route_by_id[route_id]['pole_ids'])}件）"
                ),
            )
            selected_route = route_by_id[selected_route_id]
            st.session_state.pop("explore_cms_target_stop", None)
            st.session_state.pop("explore_cms_target_route", None)

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

            existing_captions: dict[str, str] = {}
            existing_captions_en: dict[str, str] = {}
            if existing and existing["images"]:
                st.subheader("登録済みの写真")
                st.caption("既存写真のキャプションもここで直接編集できます。")
                for image in existing["images"]:
                    filename = image["file"]
                    image_path = IMAGES_DIR / filename
                    st.image(
                        str(image_path),
                        caption=image["caption"] or filename,
                        width=320,
                    )
                    caption_col, caption_en_col = st.columns(2)
                    existing_captions[filename] = caption_col.text_input(
                        "キャプション（日本語）",
                        value=image["caption"],
                        key=f"existing_caption::{widget_scope}::{filename}",
                    )
                    existing_captions_en[filename] = caption_en_col.text_input(
                        "キャプション（英語・任意）",
                        value=image["caption_en"],
                        key=f"existing_caption_en::{widget_scope}::{filename}",
                    )
                    if st.button(
                        "この写真を削除",
                        key=f"delete::{widget_scope}::{filename}",
                    ):
                        try:
                            delete_group_image(
                                stop_name=selected_stop_name,
                                route_id=selected_route_id,
                                filename=filename,
                            )
                        except ExploreContentError as error:
                            st.error(str(error))
                        except Exception as error:
                            st.exception(error)
                        else:
                            st.success("写真を削除しました。")
                            st.rerun()

            upload_revision_key = f"upload_revision::{widget_scope}"
            upload_revision = st.session_state.get(upload_revision_key, 0)
            uploaded_files = st.file_uploader(
                "写真を追加（複数選択可）",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key=f"upload::{widget_scope}::{upload_revision}",
            )
            captions: list[str] = []
            captions_en: list[str] = []
            if uploaded_files:
                st.caption(
                    f"{len(uploaded_files)}枚をまとめて追加します。"
                    "キャプションは写真ごとに設定できます。"
                )
                for index, uploaded_file in enumerate(uploaded_files):
                    st.markdown(
                        f"**{index + 1}. {uploaded_file.name}**"
                    )
                    caption_col, caption_en_col = st.columns(2)
                    captions.append(
                        caption_col.text_input(
                            "キャプション（日本語）",
                            key=(
                                f"caption::{widget_scope}::{upload_revision}::{index}::"
                                f"{uploaded_file.name}"
                            ),
                        )
                    )
                    captions_en.append(
                        caption_en_col.text_input(
                            "キャプション（英語・任意）",
                            key=(
                                f"caption_en::{widget_scope}::{upload_revision}::{index}::"
                                f"{uploaded_file.name}"
                            ),
                        )
                    )

            if st.button("CSVに保存", key=f"save::{widget_scope}"):
                try:
                    filenames = save_group(
                        stop_name=selected_stop_name,
                        route_id=selected_route_id,
                        comment=comment,
                        comment_en=comment_en,
                        uploaded_files=list(uploaded_files),
                        captions=captions,
                        captions_en=captions_en,
                        existing_captions=existing_captions,
                        existing_captions_en=existing_captions_en,
                    )
                except ExploreContentError as error:
                    st.error(str(error))
                except Exception as error:
                    st.exception(error)
                else:
                    if not filenames:
                        notice = "変更を保存しました。同じ写真は重複追加しません。"
                    elif len(filenames) == 1:
                        notice = "変更と写真1枚を保存しました。"
                    else:
                        notice = f"変更と写真{len(filenames)}枚を保存しました。"
                    st.session_state[upload_revision_key] = upload_revision + 1
                    st.session_state["explore_cms_save_notice"] = notice
                    st.rerun()

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
