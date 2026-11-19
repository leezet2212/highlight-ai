"""Deploy this repo to a Hugging Face Space (run by .github/workflows/deploy-hf.yml).

- Creates the Space (Docker SDK) if it doesn't exist yet.
- Copies GEMINI_API_KEY / ELEVENLABS_API_KEY / APP_PASSWORD from GitHub secrets
  into the Space's secrets, so the user only enters keys in one place.
- Uploads the code (git-tracked files only) with the Space README header.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from huggingface_hub import HfApi

SECRETS = ["GEMINI_API_KEY", "ELEVENLABS_API_KEY", "APP_PASSWORD"]
ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        print("::warning::Chưa có secret HF_TOKEN trên GitHub – bỏ qua bước đưa lên web.")
        return 0
    api = HfApi(token=token)
    space = os.getenv("HF_SPACE", "").strip() or f"{api.whoami()['name']}/highlight-ai"

    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    print(f"Space: {space}")

    # Upload first: the README header (sdk: docker) also converts a Space that
    # was created by hand as Static/Gradio into a Docker Space. Static Spaces
    # refuse secrets, so secrets can only be added after this.
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=archive, check=True)
        out = Path(tmp)
        header = (out / "deploy" / "hf-header.md").read_text("utf-8")
        readme = out / "README.md"
        readme.write_text(header + readme.read_text("utf-8"), "utf-8")
        api.upload_folder(
            repo_id=space, repo_type="space", folder_path=out,
            ignore_patterns=["deploy/**", ".github/**", "CLAUDE.md"],
            delete_patterns=["*"],  # remove files that no longer exist in GitHub
            commit_message=f"Deploy {os.getenv('GITHUB_SHA', 'local')[:7]} from GitHub",
        )
    print("  ✓ đã đưa code lên Space (loại Docker)")

    for name in SECRETS:
        value = os.getenv(name, "").strip()
        if not value:
            print(f"  - không có {name} trên GitHub, giữ nguyên giá trị cũ trên Space (nếu có)")
            continue
        for attempt in range(6):  # SDK change may take a few seconds to apply
            try:
                api.add_space_secret(space, name, value)
                print(f"  ✓ đã cập nhật secret {name}")
                break
            except Exception as exc:
                if attempt == 5:
                    print(f"::error::Không thêm được secret {name} vào Space: {exc}")
                    return 1
                time.sleep(5)
    if not os.getenv("APP_PASSWORD", "").strip():
        print("::warning::Chưa đặt APP_PASSWORD – nếu Space chưa có mật khẩu, ai có link cũng dùng được.")

    print(f"Đã cập nhật: https://huggingface.co/spaces/{space}")
    print("Space đang build (3-5 phút), sau đó mở link trên để dùng.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
