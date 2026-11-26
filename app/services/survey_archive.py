from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

PACKAGE_LIMIT = 512 * 1024**2


def upload_entries(files):
    """Yield ordinary uploads and ZIP members as streams, preserving relative paths."""
    expanded = count = 0
    for upload in files:
        name = upload.filename or ""
        if not name.lower().endswith(".zip"):
            yield name, upload.file
            continue
        try:
            with ZipFile(upload.file) as archive:
                for entry in archive.infolist():
                    path = PurePosixPath(entry.filename.replace("\\", "/"))
                    if (
                        entry.is_dir()
                        or "__MACOSX" in path.parts
                        or path.name.startswith(".")
                    ):
                        continue
                    count += 1
                    expanded += entry.file_size
                    if expanded > PACKAGE_LIMIT or count > 4096:
                        raise ValueError("Архив превышает лимит загрузки")
                    if entry.flag_bits & 1:
                        raise ValueError("Зашифрованные архивы не поддерживаются")
                    with archive.open(entry) as stream:
                        yield str(path), stream
        except (BadZipFile, NotImplementedError) as exc:
            raise ValueError(f"Не удалось прочитать ZIP {name}") from exc
