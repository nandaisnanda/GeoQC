# AGENTS.md

## Proyek

GeoQC: toolkit QC data geospasial. Satu engine, banyak surface (Python API, CLI,
web, plugin QGIS). Roadmap ada di [docs/roadmap.md](docs/roadmap.md).

## Prinsip yang tidak boleh dilanggar

- Data sumber tidak pernah diubah diam-diam. Repair selalu ke output baru,
  bisa di-preview dan di-undo.
- ML hanya menyarankan atau mengurutkan. Tidak pernah menghapus temuan dan
  tidak pernah repair otomatis tanpa persetujuan user.
- Setiap klaim di README/docs harus punya bukti (angka, tes, atau tautan).

## Cara kerja

- Satu tugas = satu branch = satu PR. Jangan push langsung ke main.
- Baca hanya file yang relevan dengan tugas. Jangan refactor di luar lingkup.
- Tugas besar: tulis rencana dulu, lalu berhenti dan tunggu persetujuan.
- Sebelum PR: `uv run ruff format --check .`, `uv run ruff check .`,
  `uv run mypy src tests`, `uv run pytest` harus lolos. Untuk apps/web:
  `npm --prefix apps/web run check`.
- Setiap bug yang diperbaiki wajib punya tes yang gagal sebelum perbaikan.
- Perubahan yang terlihat user dicatat di CHANGELOG.md.

## Commit

- Gaya conventional commits (feat:, fix:, chore:, docs:, test:, refactor:).
- Jangan tambahkan trailer Co-Authored-By atau baris "Generated with".

## Format laporan akhir (maksimal 10 baris)

1. Apa yang berubah (file utama)
2. Hasil tes/lint/mypy
3. Link PR
4. Hal yang belum selesai atau perlu keputusan user
