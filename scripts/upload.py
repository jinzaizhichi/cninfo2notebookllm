#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Upload PDF files to NotebookLM using notebooklm-py CLI

Prerequisites:
  pip install notebooklm-py playwright
  playwright install chromium
  notebooklm login  # Authenticate first
"""

import sys
import os
import subprocess
import json
import shutil
import time


def check_notebooklm_installed() -> bool:
    """Check if notebooklm CLI is installed"""
    return shutil.which("notebooklm") is not None


def run_notebooklm_command(args: list, timeout: int = 300) -> tuple:
    """Run notebooklm command and return (success, output)"""
    try:
        result = subprocess.run(
            ["notebooklm"] + args, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def create_notebook(title: str) -> str:
    """Create a new NotebookLM notebook, returns notebook ID or None"""
    print(f"📚 Creating notebook: {title}")

    success, output = run_notebooklm_command(["create", title])

    if not success:
        print(f"❌ Failed to create notebook: {output}", file=sys.stderr)
        return None

    # Parse output to find notebook ID
    # Output format: "Created notebook: <title> (ID: <id>)" or similar
    for line in output.split("\n"):
        if "ID:" in line or "id:" in line:
            # Extract ID from line
            import re

            match = re.search(r"[a-f0-9-]{36}", line)
            if match:
                notebook_id = match.group(0)
                print(f"✅ Created notebook: {notebook_id}")
                return notebook_id
        # Also check for UUID-like patterns
        import re

        match = re.search(r"[a-f0-9-]{36}", line)
        if match:
            notebook_id = match.group(0)
            print(f"✅ Created notebook: {notebook_id}")
            return notebook_id

    # Fallback: return trimmed output
    print(f"⚠️ Output: {output}")
    return output.strip().split()[-1] if output.strip() else None


def upload_source(notebook_id: str, file_path: str, max_retries: int = 3) -> bool:
    """Upload a file as source to a notebook with retry logic"""
    filename = os.path.basename(file_path)
    print(f"📤 Uploading: {filename}")

    for attempt in range(1, max_retries + 1):
        # Set notebook context first
        success, output = run_notebooklm_command(["use", notebook_id])
        if not success:
            if attempt < max_retries:
                print(f"   ⚠️ Attempt {attempt}/{max_retries} failed to set notebook, retrying...")
                time.sleep(3 * attempt)
                continue
            print(f"❌ Failed to set notebook: {output}", file=sys.stderr)
            return False

        # Add source -- explicitly set --type file for PDFs since auto-detect
        # only recognizes .txt/.md and treats PDFs as inline text (which fails)
        cmd = ["source", "add", file_path]
        if file_path.lower().endswith(".pdf"):
            cmd.extend(["--type", "file"])
        success, output = run_notebooklm_command(cmd)

        if success:
            print(f"   ✅ Uploaded successfully")
            return True
        else:
            if attempt < max_retries:
                wait = 5 * attempt
                print(f"   ⚠️ Attempt {attempt}/{max_retries} failed, retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"   ❌ Failed after {max_retries} attempts: {output}", file=sys.stderr)
                return False

    return False


def upload_all_sources(notebook_id: str, files: list) -> dict:
    """Upload multiple files to a notebook"""
    results = {"success": [], "failed": []}

    for i, file_path in enumerate(files):
        if upload_source(notebook_id, file_path):
            results["success"].append(file_path)
        else:
            results["failed"].append(file_path)

        # Delay between uploads to avoid rate limiting (skip after last file)
        if i < len(files) - 1:
            time.sleep(3)

    return results


def cleanup_temp_files(files: list, temp_dir: str = None):
    """Remove temporary files after upload"""
    for f in files:
        try:
            os.remove(f)
        except Exception:
            pass

    if temp_dir and (temp_dir.startswith("/var/folders") or "/tmp/" in temp_dir):
        try:
            shutil.rmtree(temp_dir)
            print(f"🧹 Cleaned up temp directory: {temp_dir}")
        except Exception:
            pass


def configure_notebook(notebook_id: str, prompt_file: str) -> bool:
    """Configure notebook with custom prompt"""
    if not os.path.exists(prompt_file):
        print(f"⚠️ Prompt file not found: {prompt_file}")
        return False

    try:
        with open(prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read()
    except Exception as e:
        print(f"❌ Error reading prompt file: {e}")
        return False

    print(f"⚙️ Configuring notebook with custom prompt...")
    # --persona takes TEXT, so we pass the content directly
    # We also set mode to 'detailed' and response-length to 'longer' for depth
    success, output = run_notebooklm_command(
        [
            "configure",
            "--notebook",
            notebook_id,
            "--persona",
            prompt,
            "--response-length",
            "longer",
        ]
    )

    if success:
        print(f"   ✅ Configuration successful")
        return True
    else:
        print(f"   ❌ Configuration failed: {output}", file=sys.stderr)
        return False


def main():
    """Main entry point"""
    if len(sys.argv) < 3:
        print("Usage: python upload.py <notebook_title> <pdf_file1> [pdf_file2] ...")
        print("       python upload.py <notebook_title> --json <json_file>")
        print("")
        print("The JSON file should contain output from download.py")
        sys.exit(1)

    # Check notebooklm is installed
    if not check_notebooklm_installed():
        print("❌ NotebookLM CLI not found!", file=sys.stderr)
        print("Install with: pip install notebooklm-py playwright")
        print("Then: playwright install chromium")
        print("Then authenticate with: notebooklm login")
        sys.exit(1)

    notebook_title = sys.argv[1]

    # Handle JSON input from download.py
    if sys.argv[2] == "--json":
        json_file = sys.argv[3]
        with open(json_file, "r") as f:
            data = json.load(f)
        files = data.get("files", [])
        temp_dir = data.get("output_dir")
        notebook_title = f"{data.get('stock_name', notebook_title)} 财务报告"
    else:
        files = sys.argv[2:]
        temp_dir = None

    if not files:
        print("❌ No files to upload", file=sys.stderr)
        sys.exit(1)

    print(f"📁 Files to upload: {len(files)}")

    # Create notebook
    notebook_id = create_notebook(notebook_title)
    if not notebook_id:
        sys.exit(1)

    # Upload all files
    results = upload_all_sources(notebook_id, files)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"✅ Uploaded: {len(results['success'])} files")
    if results["failed"]:
        print(f"❌ Failed: {len(results['failed'])} files")
    print(f"📚 Notebook: {notebook_title}")
    print(f"🆔 ID: {notebook_id}")

    # Cleanup temp files
    if temp_dir:
        cleanup_temp_files(files, temp_dir)

    # Output JSON result
    result = {
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "uploaded": len(results["success"]),
        "failed": len(results["failed"]),
    }
    print("\n---JSON_OUTPUT---")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
