#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import streamlit as st


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


def save_group(
    *,
    stop_name: str,
    route_id: str,
    comment: str,
    uploaded_file,
    caption: str,
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
                images.append({"file": new_filename, "caption": caption})
            if not comment and not images:
                raise ExploreContentError(
                    "comment or image is required for a new entry"
                )
            groups.append(
                {
                    "stop_name": stop_name,
                    "route_id": route_id,
                    "comment": comment,
                    "images": images,
                }
            )
        else:
            group = {
                "stop_name": groups[group_index]["stop_name"],
                "route_id": groups[group_index]["route_id"],
                "comment": comment,
                "images": [
                    dict(image) for image in groups[group_index]["images"]
                ],
            }
            if new_filename is not None:
                group["images"].append(
                    {"file": new_filename, "caption": caption}
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
                "コメント",
                value=existing["comment"] if existing else "",
                height=120,
                key=f"comment::{widget_scope}",
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

            uploaded = st.file_uploader(
                "写真を追加",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=False,
                key=f"upload::{widget_scope}",
            )
            caption = st.text_input(
                "追加する写真のキャプション",
                disabled=uploaded is None,
                key=f"caption::{widget_scope}",
            )

            if st.button("CSVに保存", key=f"save::{widget_scope}"):
                try:
                    filename = save_group(
                        stop_name=selected_stop_name,
                        route_id=selected_route_id,
                        comment=comment,
                        uploaded_file=uploaded,
                        caption=caption,
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
