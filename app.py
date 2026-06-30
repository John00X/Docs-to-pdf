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
    page_title="DOCs-PDFs Converter & Merger",
    page_icon="📄",
    layout="centered",
)

st.markdown("""
<style>
    .block-container { max-width: 820px; }
    .stAlert { border-radius: 8px; }
    div[data-testid="stFileUploader"] { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)


# ── LibreOffice check ─────────────────────────────────────────────────────────
@st.cache_resource
def check_libreoffice():
    for cmd in ("libreoffice", "soffice"):
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=15)
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
        "**`packages.txt`** must exist in your repo root and contain:\n"
        "```\nlibreoffice\n```\n"
        "After adding it, go to Streamlit Cloud → **Manage app** → **Reboot app**.\n\n"
        f"**Server says:** `{lo_info}`"
    )
    st.stop()


# ── Core helpers ──────────────────────────────────────────────────────────────

def convert_doc_to_pdf(input_path: Path, output_dir: Path) -> Path | None:
    """Convert a .doc/.docx file to PDF using LibreOffice. Returns PDF path or None."""
    try:
        result = subprocess.run(
            [LO_CMD, "--headless", "--norestore", "--nofirststartwizard",
             "--convert-to", "pdf", "--outdir", str(output_dir), str(input_path)],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        st.error(f"❌ `{LO_CMD}` not found.")
        return None
    except subprocess.TimeoutExpired:
        st.error(f"❌ Conversion timed out for `{input_path.name}`.")
        return None

    if result.returncode != 0:
        st.error(f"❌ LibreOffice error for **{input_path.name}**:\n```\n{result.stderr or result.stdout}\n```")
        return None

    expected = output_dir / (input_path.stem + ".pdf")
    if expected.exists():
        return expected
    candidates = list(output_dir.glob("*.pdf"))
    if candidates:
        return candidates[0]
    st.error(f"❌ PDF not produced for `{input_path.name}`.")
    return None


def merge_pdf_files(pdf_paths: list[Path], output_path: Path) -> bool:
    """Merge multiple PDFs into one using pypdf."""
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


def file_type_badge(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        return "🔴 PDF"
    elif ext in (".doc", ".docx"):
        return "🔵 Word"
    return "📄"


# ── UI Header ─────────────────────────────────────────────────────────────────
st.title("📄 Doc & PDF Toolkit")
st.caption(f"Convert Word docs → PDF · Merge PDFs · Merge mixed Word + PDF files into one PDF  \n✅ LibreOffice ready: `{lo_info}`")
st.divider()

# ── Tab layout ────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs([
    "🔄  Convert Word → PDF",
    "🔗  Merge PDFs",
    "🗂️  Merge Mixed Files (Word + PDF)",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Convert Word docs → PDF (individually or merged)
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Convert Word Documents to PDF")
    st.caption("Upload `.doc` / `.docx` files. Get them back as separate PDFs (ZIP) or one merged PDF.")

    t1_files = st.file_uploader(
        "Upload Word files",
        type=["doc", "docx"],
        accept_multiple_files=True,
        key="tab1_uploader",
    )

    if t1_files:
        st.success(f"**{len(t1_files)} file(s) selected:** {', '.join(f.name for f in t1_files)}")

    t1_mode = st.radio(
        "Output mode",
        options=["Download as separate PDFs (ZIP)", "Merge into one PDF"],
        horizontal=True,
        key="tab1_mode",
    )

    t1_btn = st.button("🚀 Convert", type="primary", disabled=not t1_files,
                        use_container_width=True, key="tab1_btn")

    if t1_btn and t1_files:
        tmp = tempfile.mkdtemp(prefix="t1_")
        try:
            up_dir  = Path(tmp) / "uploads"
            pdf_dir = Path(tmp) / "pdfs"
            out_dir = Path(tmp) / "output"
            up_dir.mkdir(); pdf_dir.mkdir(); out_dir.mkdir()

            saved = []
            for uf in t1_files:
                dest = up_dir / uf.name
                dest.write_bytes(uf.read())
                saved.append(dest)

            converted: list[Path] = []
            bar = st.progress(0, text="Starting…")
            for i, doc in enumerate(saved):
                bar.progress(i / len(saved), text=f"Converting {doc.name} ({i+1}/{len(saved)})…")
                with st.spinner(f"Converting `{doc.name}`…"):
                    pdf = convert_doc_to_pdf(doc, pdf_dir)
                if pdf:
                    converted.append(pdf)
                    st.write(f"✅ `{doc.name}` → `{pdf.name}`")
                else:
                    st.write(f"⚠️ `{doc.name}` — failed (skipped)")
            bar.progress(1.0, text="Done!")

            if not converted:
                st.error("No files converted successfully.")
            else:
                st.divider()
                if t1_mode.startswith("Download as separate"):
                    zp = out_dir / "converted_pdfs.zip"
                    build_zip(converted, zp)
                    st.success(f"🎉 {len(converted)} PDF(s) ready in ZIP!")
                    st.download_button("⬇️ Download ZIP", zp.read_bytes(),
                                       "converted_pdfs.zip", "application/zip",
                                       type="primary", use_container_width=True)
                else:
                    mp = out_dir / "merged_output.pdf"
                    with st.spinner("Merging…"):
                        ok = merge_pdf_files(converted, mp)
                    if ok:
                        st.success(f"🎉 {len(converted)} PDF(s) merged!")
                        st.download_button("⬇️ Download Merged PDF", mp.read_bytes(),
                                           "merged_output.pdf", "application/pdf",
                                           type="primary", use_container_width=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Merge PDFs only
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Merge PDF Files")
    st.caption("Upload multiple PDFs. They will be stitched together **in the order shown** into one PDF.")

    t2_files = st.file_uploader(
        "Upload PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        key="tab2_uploader",
    )

    if t2_files:
        st.info(f"**{len(t2_files)} PDF(s) will be merged in this order:**")
        for i, f in enumerate(t2_files, 1):
            size_kb = round(len(f.getvalue()) / 1024, 1)
            st.write(f"  {i}. 🔴 `{f.name}` — {size_kb} KB")

    t2_btn = st.button("🔗 Merge PDFs", type="primary",
                        disabled=not t2_files or len(t2_files) < 2,
                        use_container_width=True, key="tab2_btn")

    if t2_files and len(t2_files) < 2:
        st.warning("⚠️ Please upload at least 2 PDF files to merge.")

    if t2_btn and t2_files and len(t2_files) >= 2:
        tmp = tempfile.mkdtemp(prefix="t2_")
        try:
            up_dir  = Path(tmp) / "uploads"
            out_dir = Path(tmp) / "output"
            up_dir.mkdir(); out_dir.mkdir()

            saved: list[Path] = []
            for uf in t2_files:
                dest = up_dir / uf.name
                dest.write_bytes(uf.read())
                saved.append(dest)

            merged_path = out_dir / "merged_output.pdf"
            with st.spinner(f"Merging {len(saved)} PDFs…"):
                ok = merge_pdf_files(saved, merged_path)

            if ok:
                st.success(f"🎉 {len(saved)} PDFs merged successfully!")
                st.download_button("⬇️ Download Merged PDF", merged_path.read_bytes(),
                                   "merged_output.pdf", "application/pdf",
                                   type="primary", use_container_width=True)
            else:
                st.error("Merging failed. See errors above.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Merge Mixed Files (Word + PDF) into one PDF
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("Merge Mixed Files — Word + PDF → Single PDF")
    st.caption(
        "Upload any mix of `.doc`, `.docx`, and `.pdf` files. "
        "Word files are auto-converted first, then **all files are merged in upload order** into one PDF."
    )

    t3_files = st.file_uploader(
        "Upload Word and/or PDF files",
        type=["doc", "docx", "pdf"],
        accept_multiple_files=True,
        key="tab3_uploader",
    )

    if t3_files:
        word_count = sum(1 for f in t3_files if Path(f.name).suffix.lower() in (".doc", ".docx"))
        pdf_count  = sum(1 for f in t3_files if Path(f.name).suffix.lower() == ".pdf")
        st.info(
            f"**{len(t3_files)} file(s) selected** — "
            f"🔵 {word_count} Word  ·  🔴 {pdf_count} PDF  \n"
            f"Word files will be converted to PDF first, then everything is merged in order."
        )
        st.write("**Merge order:**")
        for i, f in enumerate(t3_files, 1):
            size_kb = round(len(f.getvalue()) / 1024, 1)
            badge = file_type_badge(f.name)
            st.write(f"  {i}. {badge} `{f.name}` — {size_kb} KB")

    t3_output_name = st.text_input(
        "Output filename (optional)",
        value="merged_output.pdf",
        key="t3_output_name",
        help="Name for the final merged PDF file",
    )
    if not t3_output_name.endswith(".pdf"):
        t3_output_name += ".pdf"

    t3_btn = st.button("🗂️ Convert & Merge All", type="primary",
                        disabled=not t3_files or len(t3_files) < 2,
                        use_container_width=True, key="tab3_btn")

    if t3_files and len(t3_files) < 2:
        st.warning("⚠️ Please upload at least 2 files to merge.")

    if t3_btn and t3_files and len(t3_files) >= 2:
        tmp = tempfile.mkdtemp(prefix="t3_")
        try:
            up_dir  = Path(tmp) / "uploads"
            pdf_dir = Path(tmp) / "pdfs"
            out_dir = Path(tmp) / "output"
            up_dir.mkdir(); pdf_dir.mkdir(); out_dir.mkdir()

            # Save all files to disk in order
            saved: list[Path] = []
            for uf in t3_files:
                dest = up_dir / uf.name
                dest.write_bytes(uf.read())
                saved.append(dest)

            # Process each file — convert Word, pass PDFs through
            all_pdfs: list[Path] = []
            bar = st.progress(0, text="Processing files…")

            for i, fpath in enumerate(saved):
                ext = fpath.suffix.lower()
                bar.progress(i / len(saved), text=f"Processing `{fpath.name}` ({i+1}/{len(saved)})…")

                if ext in (".doc", ".docx"):
                    with st.spinner(f"Converting Word → PDF: `{fpath.name}`…"):
                        pdf = convert_doc_to_pdf(fpath, pdf_dir)
                    if pdf:
                        all_pdfs.append(pdf)
                        st.write(f"✅ `{fpath.name}` → converted to PDF")
                    else:
                        st.write(f"⚠️ `{fpath.name}` — conversion failed (skipped)")

                elif ext == ".pdf":
                    # Copy PDF to pdf_dir to avoid filename conflicts
                    dest_pdf = pdf_dir / fpath.name
                    shutil.copy2(fpath, dest_pdf)
                    all_pdfs.append(dest_pdf)
                    st.write(f"✅ `{fpath.name}` — added directly (PDF)")

            bar.progress(1.0, text="All files ready. Merging…")

            if not all_pdfs:
                st.error("No files could be processed. See errors above.")
            elif len(all_pdfs) == 1:
                # Only one PDF produced — just download it directly
                st.warning("Only 1 file was successfully processed — downloading it directly.")
                st.download_button("⬇️ Download PDF", all_pdfs[0].read_bytes(),
                                   t3_output_name, "application/pdf",
                                   type="primary", use_container_width=True)
            else:
                merged_path = out_dir / t3_output_name
                with st.spinner(f"Merging {len(all_pdfs)} PDFs into one…"):
                    ok = merge_pdf_files(all_pdfs, merged_path)

                if ok:
                    st.divider()
                    st.success(
                        f"🎉 **{len(all_pdfs)} files merged** into `{t3_output_name}`!  \n"
                        f"({word_count} Word doc(s) converted + {pdf_count} PDF(s) passed through)"
                    )
                    st.download_button(
                        f"⬇️ Download {t3_output_name}",
                        merged_path.read_bytes(),
                        t3_output_name,
                        "application/pdf",
                        type="primary",
                        use_container_width=True,
                    )
                else:
                    st.error("Merging failed. See errors above.")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.divider()
st.caption("Powered by LibreOffice · pypdf · Streamlit")
