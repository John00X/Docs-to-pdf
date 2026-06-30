import streamlit as st
import subprocess
import tempfile
import os
import zipfile
import shutil
from pathlib import Path
from pypdf import PdfWriter, PdfReader

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Word → PDF Converter",
    page_icon="📄",
    layout="centered",
)

st.markdown("""
<style>
    .block-container { max-width: 780px; }
    .stAlert { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ── LibreOffice availability check (runs once at startup) ─────────────────────
@st.cache_resource
def check_libreoffice() -> tuple[bool, str]:
    """Return (available, version_string_or_error)."""
    # Try common binary names
    for cmd in ("libreoffice", "soffice"):
        try:
            r = subprocess.run(
                [cmd, "--version"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                return True, r.stdout.strip(), cmd
        except FileNotFoundError:
            continue
        except Exception as e:
            return False, str(e), cmd
    return False, "LibreOffice binary not found", "libreoffice"

lo_ok, lo_info, LO_CMD = check_libreoffice()

if not lo_ok:
    st.error(
        "### ❌ LibreOffice is not installed on this server\n\n"
        "**How to fix — check your GitHub repo for these files:**\n\n"
        "**`packages.txt`** must exist and contain exactly:\n"
        "```\nlibreoffice\n```\n\n"
        "**Common causes:**\n"
        "- `packages.txt` is missing from the repo root\n"
        "- The file is named wrongly (e.g. `package.txt` or `Packages.txt`)\n"
        "- The file has Windows line endings — re-save with LF endings\n"
        "- The app was deployed *before* `packages.txt` was added — **reboot the app** "
        "from the Streamlit Cloud dashboard (☰ → Reboot app)\n\n"
        f"**Server says:** `{lo_info}`"
    )
    st.info(
        "After fixing, go to your Streamlit Cloud dashboard → **Manage app** "
        "(lower-right corner) → **Reboot app** to force a fresh install."
    )
    st.stop()

# ── Helper functions ──────────────────────────────────────────────────────────

def convert_to_pdf(input_path: Path, output_dir: Path) -> Path | None:
    try:
        result = subprocess.run(
            [
                LO_CMD,
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
                str(input_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        st.error(f"❌ `{LO_CMD}` not found. See the fix instructions above.")
        return None
    except subprocess.TimeoutExpired:
        st.error(f"❌ Conversion timed out for `{input_path.name}` (> 120 s).")
        return None

    if result.returncode != 0:
        st.error(
            f"❌ LibreOffice error for **{input_path.name}** "
            f"(exit {result.returncode}):\n```\n{result.stderr or result.stdout}\n```"
        )
        return None

    expected_pdf = output_dir / (input_path.stem + ".pdf")
    if not expected_pdf.exists():
        # LO sometimes lowercases the stem
        candidates = list(output_dir.glob("*.pdf"))
        if candidates:
            return candidates[0]
        st.error(f"❌ PDF not produced for `{input_path.name}`. stderr: {result.stderr}")
        return None

    return expected_pdf


def merge_pdfs(pdf_paths: list[Path], output_path: Path) -> bool:
    writer = PdfWriter()
    for pdf in pdf_paths:
        try:
            reader = PdfReader(str(pdf))
            for page in reader.pages:
                writer.add_page(page)
        except Exception as exc:
            st.error(f"❌ Could not read `{pdf.name}`: {exc}")
            return False
    with open(output_path, "wb") as fh:
        writer.write(fh)
    return True


def build_zip(pdf_paths: list[Path], zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for pdf in pdf_paths:
            zf.write(pdf, arcname=pdf.name)


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("📄 Word → PDF Converter")
st.caption(
    f"Upload `.doc` / `.docx` files and convert them to PDF — "
    f"individually or merged into one.  \n"
    f"✅ LibreOffice ready: `{lo_info}`"
)

st.divider()

uploaded_files = st.file_uploader(
    "Drag & drop your Word documents here, or click to browse",
    type=["doc", "docx"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.success(f"**{len(uploaded_files)} file(s) ready:** {', '.join(f.name for f in uploaded_files)}")

st.divider()

mode = st.radio(
    "Conversion mode",
    options=["Convert Individually (download as ZIP)", "Merge into Single PDF"],
    index=0,
    horizontal=True,
)

st.divider()

convert_btn = st.button(
    "🚀 Start Conversion",
    type="primary",
    disabled=not uploaded_files,
    use_container_width=True,
)

# ── Conversion logic ──────────────────────────────────────────────────────────

if convert_btn and uploaded_files:
    tmp_dir = tempfile.mkdtemp(prefix="word2pdf_")

    try:
        upload_dir = Path(tmp_dir) / "uploads"
        pdf_dir    = Path(tmp_dir) / "pdfs"
        out_dir    = Path(tmp_dir) / "output"
        upload_dir.mkdir(); pdf_dir.mkdir(); out_dir.mkdir()

        # Save uploads to disk
        saved_paths: list[Path] = []
        for uf in uploaded_files:
            dest = upload_dir / uf.name
            dest.write_bytes(uf.read())
            saved_paths.append(dest)

        # Convert each file
        converted_pdfs: list[Path] = []
        progress_bar = st.progress(0, text="Starting conversion…")

        for idx, doc_path in enumerate(saved_paths):
            progress_bar.progress(
                idx / len(saved_paths),
                text=f"Converting **{doc_path.name}** ({idx + 1}/{len(saved_paths)})…",
            )
            with st.spinner(f"Converting `{doc_path.name}`…"):
                pdf_path = convert_to_pdf(doc_path, pdf_dir)

            if pdf_path:
                converted_pdfs.append(pdf_path)
                st.write(f"✅ `{doc_path.name}` → `{pdf_path.name}`")
            else:
                st.write(f"⚠️ `{doc_path.name}` — conversion failed (skipped)")

        progress_bar.progress(1.0, text="Conversion complete!")

        if not converted_pdfs:
            st.error("No files were successfully converted. See errors above.")
            st.stop()

        st.divider()

        if mode.startswith("Convert Individually"):
            zip_path = out_dir / "converted_pdfs.zip"
            build_zip(converted_pdfs, zip_path)
            st.success(f"🎉 **{len(converted_pdfs)} PDF(s)** packed into `converted_pdfs.zip`!")
            st.download_button(
                label="⬇️  Download ZIP",
                data=zip_path.read_bytes(),
                file_name="converted_pdfs.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )
        else:
            merged_path = out_dir / "merged_output.pdf"
            with st.spinner("Merging PDFs…"):
                ok = merge_pdfs(converted_pdfs, merged_path)
            if ok:
                st.success(f"🎉 **{len(converted_pdfs)} PDF(s)** merged into `merged_output.pdf`!")
                st.download_button(
                    label="⬇️  Download Merged PDF",
                    data=merged_path.read_bytes(),
                    file_name="merged_output.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.error("Merging failed. See errors above.")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

elif convert_btn and not uploaded_files:
    st.warning("⚠️ Please upload at least one Word document first.")

st.divider()
st.caption("Conversion powered by LibreOffice · Merging powered by pypdf · Built with Streamlit")
