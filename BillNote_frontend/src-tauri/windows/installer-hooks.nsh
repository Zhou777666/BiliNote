; CUDA and the Python runtime exceed 2 GiB before compression. Tauri's default
; /SOLID compressor maps the entire payload and fails in NSIS 3.11. Compress
; each file independently instead. Keep this before any File/ReserveFile data.
; /FINAL prevents a later template directive from restoring solid compression.
SetCompressor /FINAL lzma
