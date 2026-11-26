from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

PACKAGE_LIMIT = 512 * 1024**2


def generated_reports(names):
    paths = {PurePosixPath(n.replace("\\", "/")) for n in names}
    roots = {
        p.parent
        for p in paths
        if p.name == "manifest.json" and p.with_name("validation.json") in paths
    }
    return {
        p
        for p in paths
        if p.parent in roots
        and p.name == "validation.json"
        or any(
            parent.name == "review" and parent.parent in roots for parent in p.parents
        )
    }


def upload_entries(files):
    """Yield ordinary uploads and ZIP members as streams, preserving relative paths."""
    expanded = count = 0
    reports = generated_reports(f.filename or "" for f in files)
    for upload in files:
        name = upload.filename or ""
        if not name.lower().endswith(".zip"):
            if PurePosixPath(name.replace("\\", "/")) not in reports:
                yield name, upload.file
            continue
        try:
            with ZipFile(upload.file) as archive:
                archive_reports = generated_reports(archive.namelist())
                for entry in archive.infolist():
                    path = PurePosixPath(entry.filename.replace("\\", "/"))
                    if (
                        entry.is_dir()
                        or path in archive_reports
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
