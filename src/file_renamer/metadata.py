"""Read-only metadata expansion with explicit tag names and cached source identities."""

import email.policy
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import zipfile
import zlib
from datetime import datetime, timezone
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from .date_formats import format_date

ASSETS = Path(__file__).parent / "assets"
CATALOG = json.loads((ASSETS / "metadata-tags.json").read_text(encoding="utf-8"))


def tool_path(name):
    filename = name + (".exe" if os.name == "nt" else "")
    for path in (ASSETS / "tools" / filename, Path(__file__).resolve().parents[2] / "build" / "tools" / filename):
        if path.exists():
            return str(path)
    return shutil.which(name)


def child_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def torrent_data(data):
    spans = {}

    def parse(pos, depth=0):
        if depth > 100:
            raise ValueError("Torrent nesting is too deep")
        start = pos
        if data[pos : pos + 1] == b"i":
            end = data.index(b"e", pos)
            return int(data[pos + 1 : end]), end + 1
        if data[pos : pos + 1] in (b"l", b"d"):
            dictionary = data[pos : pos + 1] == b"d"
            out = {} if dictionary else []
            pos += 1
            while data[pos : pos + 1] != b"e":
                key, pos = parse(pos, depth + 1)
                if dictionary:
                    begin = pos
                    val, pos = parse(pos, depth + 1)
                    out[key] = val
                    if depth == 0:
                        spans[key] = data[begin:pos]
                else:
                    out.append(key)
            return out, pos + 1
        colon = data.index(b":", pos)
        length = int(data[pos:colon])
        end = colon + 1 + length
        if end > len(data) or end <= start:
            raise ValueError("Invalid torrent value")
        return data[colon + 1 : end], end

    root, _ = parse(0)
    info = root.get(b"info", {})
    files = info.get(b"files", [])
    size = sum(f.get(b"length", 0) for f in files) if files else info.get(b"length", 0)
    result = {
        "Name": info.get(b"name.utf-8", info.get(b"name", b"")).decode("utf-8", "replace"),
        "Announce": root.get(b"announce", b"").decode("utf-8", "replace"),
        "Comment": root.get(b"comment", b"").decode("utf-8", "replace"),
        "Publisher": root.get(b"publisher", b"").decode("utf-8", "replace"),
        "CountFiles": len(files) or 1,
        "Hash": hashlib.sha1(spans.get(b"info", b"")).hexdigest(),
        "TotalSizeBytes": size,
        "TotalSize": size,
    }
    for suffix, divisor in (("KB", 1024), ("MB", 1024**2), ("GB", 1024**3)):
        result["TotalSize" + suffix] = f"{size / divisor:.2f}"
    if root.get(b"creation date"):
        dt = datetime.fromtimestamp(root[b"creation date"], timezone.utc)
        result["CreationDateUTC"] = dt.strftime("%Y-%m-%d %H-%M-%S")
        result["CreationDateLocal"] = dt.astimezone().strftime("%Y-%m-%d %H-%M-%S")
    return result


def android_data(path):
    with zipfile.ZipFile(path) as archive:
        if archive.getinfo("AndroidManifest.xml").file_size > 4 * 1024 * 1024:
            raise ValueError("Android manifest is too large")
        raw = archive.read("AndroidManifest.xml")
        architectures = sorted(
            {p.split("/")[1] for p in archive.namelist() if p.startswith("lib/") and p.count("/") > 1}
        )
    values, permissions, strings = {}, [], []
    names = {
        "package": "Package",
        "versionName": "Version",
        "versionCode": "VersionCode",
        "label": "Label",
        "minSdkVersion": "MinSdkVersion",
        "targetSdkVersion": "TargetSdkVersion",
        "compileSdkVersion": "CompileSdkVersion",
        "compileSdkVersionCodename": "CompileSdkVersionName",
    }
    if raw.lstrip().startswith(b"<"):
        import xml.etree.ElementTree as ET

        for node in ET.fromstring(raw).iter():
            for key, value in node.attrib.items():
                key = key.rsplit("}", 1)[-1]
                if key in names:
                    values[names[key]] = value
                if node.tag.endswith("uses-permission") and key == "name":
                    permissions.append(value)
    else:
        pos = 8
        while pos + 8 <= len(raw):
            kind, header, size = struct.unpack_from("<HHI", raw, pos)
            if size < 8 or pos + size > len(raw):
                raise ValueError("Invalid APK manifest chunk")
            if kind == 1:
                count, _, flags, start, _ = struct.unpack_from("<IIIII", raw, pos + 8)

                def length(at, utf8):
                    unit = raw[at] if utf8 else struct.unpack_from("<H", raw, at)[0]
                    shift = 7 if utf8 else 15
                    width = 1 if utf8 else 2
                    if unit & (1 << shift):
                        second = raw[at + width] if utf8 else struct.unpack_from("<H", raw, at + width)[0]
                        return ((unit & ((1 << shift) - 1)) << shift) | second, at + 2 * width
                    return unit, at + width

                for i in range(count):
                    off = struct.unpack_from("<I", raw, pos + header + i * 4)[0]
                    at = pos + start + off
                    utf8 = bool(flags & 0x100)
                    if utf8:
                        _, at = length(at, True)
                    n, at = length(at, utf8)
                    strings.append(
                        raw[at : at + n * (1 if utf8 else 2)].decode("utf-8" if utf8 else "utf-16le", "replace")
                    )
            elif kind == 0x102 and strings:
                _, name_index, attr_start, attr_size, count = struct.unpack_from("<IIHHH", raw, pos + 16)
                tag = strings[name_index]
                for i in range(count):
                    at = pos + 16 + attr_start + i * attr_size
                    _, key, raw_index, _, _, value_type, data = struct.unpack_from("<IIIHBBI", raw, at)
                    name = strings[key]
                    value = (
                        strings[raw_index]
                        if raw_index != 0xFFFFFFFF
                        else strings[data]
                        if value_type == 3
                        else str(data)
                    )
                    if name in names:
                        values[names[name]] = value
                    if tag == "uses-permission" and name == "name":
                        permissions.append(value)
            pos += size
    values["Architectures"], values["Permissions"] = ", ".join(architectures), ", ".join(permissions)
    for name in ("MinSdk", "TargetSdk"):
        n = values.get(name + "Version", "")
        releases = {
            21: "Android 5.0",
            23: "Android 6.0",
            24: "Android 7.0",
            26: "Android 8.0",
            28: "Android 9",
            29: "Android 10",
            30: "Android 11",
            31: "Android 12",
            33: "Android 13",
            34: "Android 14",
            35: "Android 15",
        }
        values[name + "VersionName"] = releases.get(int(n), n) if n.isdigit() else n
    return values


CONTENT_KEYS = {
    "Album": ("Album",),
    "AlbumArtist": ("AlbumArtist", "Band"),
    "Artist": ("Artist", "Author"),
    "Title": ("Title",),
    "Genre": ("Genre",),
    "TrackNo": ("Track", "TrackNumber"),
    "TrackTotal": ("TrackTotal", "TotalTracks"),
    "DiscNo": ("DiscNumber", "PartOfSet"),
    "DiscTotal": ("DiscTotal", "TotalDiscs"),
    "DiskNo": ("DiscNumber", "PartOfSet"),
    "DiskTotal": ("DiscTotal", "TotalDiscs"),
    "PartOfSet": ("PartOfSet", "DiscNumber"),
    "Year": ("Year", "Date", "DateTimeOriginal", "ReleaseDate"),
    "Date": ("DateTimeOriginal", "CreateDate", "ModifyDate"),
    "Description": ("ImageDescription", "Description", "FileDescription"),
    "Make": ("Make",),
    "Model": ("Model",),
    "Caption": ("Caption-Abstract", "Caption"),
    "City": ("City",),
    "Headline": ("Headline",),
    "Keywords": ("Keywords", "Subject"),
    "Location": ("Sub-location", "Location"),
    "ObjectName": ("ObjectName",),
    "Author": ("Author", "Creator"),
    "Subject": ("Subject",),
    "PageCount": ("PageCount",),
    "Name": ("FontName", "Name"),
    "FamilyName": ("FontFamily", "FontFamilyName"),
    "PostScriptName": ("PostScriptName",),
    "Revision": ("FontRevision",),
    "Comments": ("Comments",),
    "Company": ("CompanyName",),
    "Copyright": ("LegalCopyright", "Copyright"),
    "FileVersion": ("FileVersion",),
    "Product": ("ProductName",),
    "ProductVersion": ("ProductVersion",),
    "Width": ("ImageWidth", "SourceImageWidth"),
    "Height": ("ImageHeight", "SourceImageHeight"),
    "VideoCodec": ("VideoCodec", "CompressorID"),
    "FramesPerSecond": ("FrameRate", "VideoFrameRate"),
    "TotalFrames": ("FrameCount", "VideoFrameCount"),
}


class Metadata:
    def __init__(self, now=None, clipboard=""):
        self.now, self.clipboard = now or datetime.now(), clipboard
        self.cache = {}

    def expand(self, text, path):
        return re.sub(r":([A-Za-z][A-Za-z0-9_]*):", lambda m: self.get(m[1], path), text)

    def values(self, path):
        if not path:
            raise ValueError("This metadata tag needs a source file")
        source = Path(path)
        info = source.stat()
        key = (str(source), info.st_size, info.st_mtime_ns)
        return self.cache.setdefault(key, {}), source, info

    def content(self, source, values):
        if "content" not in values:
            tool = tool_path("exiftool")
            if not tool:
                raise ValueError("ExifTool is unavailable; rebuild or repair the metadata tools")
            try:
                proc = subprocess.run(
                    # Personal ExifTool configs can execute Perl and add write options.
                    # Preview must use only the bundled reader's read-only defaults.
                    [tool, "-config", "", "-json", "-G1", "-n", "-charset", "filename=UTF8", "--", str(source)],
                    capture_output=True,
                    timeout=30,
                    **child_options(),
                )
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Metadata extraction exceeded 30 seconds") from exc
            try:
                records = json.loads(proc.stdout.decode("utf-8"))
                raw = records[0]
            except (ValueError, IndexError) as exc:
                raise ValueError("Metadata extraction failed") from exc
            if any(k.endswith(":Error") or k == "Error" for k in raw):
                raise ValueError(next(str(v) for k, v in raw.items() if k.endswith(":Error") or k == "Error"))
            values["content"] = raw
        return values["content"]

    def get(self, tag, path):
        tag = tag.strip(":")
        if tag not in CATALOG:
            raise ValueError(f"Unknown metadata tag: {tag}")
        if tag == "Date_Now":
            return format_date(self.now, "yyyy-mm-dd hh-nn-ss")
        if tag == "Clipboard":
            return self.clipboard
        values, source, stat = self.values(path)
        if tag in values:
            return values[tag]
        category, field = tag.split("_", 1)
        if category == "File":
            direct = {
                "BaseName": source.stem,
                "FileName": source.name,
                "FilePath": str(source),
                "Extension": source.suffix,
                "FolderName": source.parent.name,
                "FolderPath": str(source.parent),
                "GrandparentFolderName": source.parent.parent.name,
                "GrandparentFolderPath": str(source.parent.parent),
                "SizeBytes": str(stat.st_size),
                "Size": str(stat.st_size),
                "SizeKB": f"{stat.st_size / 1024:.2f}",
                "SizeMB": f"{stat.st_size / 1024**2:.2f}",
                "SizeGB": f"{stat.st_size / 1024**3:.2f}",
                "DateModified": format_date(datetime.fromtimestamp(stat.st_mtime), "yyyy-mm-dd hh-nn-ss"),
            }
            if field == "DateCreated":
                if os.name != "nt" and not hasattr(stat, "st_birthtime"):
                    raise ValueError("File creation time is unavailable on this filesystem")
                return format_date(
                    datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_ctime)), "yyyy-mm-dd hh-nn-ss"
                )
            if field == "DOSName":
                if os.name != "nt":
                    raise ValueError("DOS short names are only available on Windows")
                import ctypes

                out = ctypes.create_unicode_buffer(32768)
                if not ctypes.windll.kernel32.GetShortPathNameW(str(source), out, len(out)):
                    raise ValueError("Could not read DOS short name")
                return Path(out.value).name
            return direct.get(field, "")
        if category == "Hash":
            if "hashes" not in values:
                hashes = {name: hashlib.new(name.lower()) for name in ("MD5", "SHA1", "SHA256", "SHA512")}
                crc = 0
                with source.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        crc = zlib.crc32(block, crc)
                        for digest in hashes.values():
                            digest.update(block)
                values["hashes"] = {k: v.hexdigest() for k, v in hashes.items()} | {"CRC32": f"{crc & 0xFFFFFFFF:08x}"}
            return values["hashes"][field]
        if category == "HTML":
            with source.open("rb") as stream:
                data = stream.read(4 * 1024 * 1024).decode("utf-8", "replace")
            match = re.search(r"<title[^>]*>(.*?)</title>", data, re.I | re.S)
            return html.unescape(re.sub(r"\s+", " ", match[1]).strip()) if match else ""
        if category == "Torrent":
            if "torrent" not in values:
                if stat.st_size > 32 * 1024 * 1024:
                    raise ValueError("Torrent metadata is too large")
                values["torrent"] = torrent_data(source.read_bytes())
            return str(values["torrent"].get(field, ""))
        if category == "Android":
            if "android" not in values:
                values["android"] = android_data(source)
            return str(values["android"].get(field, ""))
        if category == "Email" and source.suffix.lower() == ".eml":
            if "email" not in values:
                with source.open("rb") as stream:
                    values["email"] = BytesParser(policy=email.policy.default).parse(stream, headersonly=True)
            message = values["email"]
            sender = getaddresses([str(message.get("From", ""))])
            recipients = getaddresses([str(message.get("To", ""))])
            if field.startswith("DateSent"):
                if not message.get("Date"):
                    return ""
                dt = parsedate_to_datetime(str(message["Date"]))
                if field == "DateSentOriginal":
                    return str(message["Date"])
                if field == "DateSentUTC":
                    dt = dt.astimezone(timezone.utc)
                return format_date(dt, "yyyy-mm-dd hh-nn-ss")
            direct = {
                "Subject": message.get("Subject", ""),
                "MessageID": message.get("Message-ID", ""),
                "Sender": message.get("From", ""),
                "SenderName": sender[0][0] if sender else "",
                "SenderEmail": sender[0][1] if sender else "",
                "Recipients": message.get("To", ""),
                "Recipient": message.get("To", ""),
                "RecipientName": recipients[0][0] if recipients else "",
                "RecipientEmail": recipients[0][1] if recipients else "",
            }
            return str(direct.get(field, ""))
        raw = self.content(source, values)

        def lookup(*keys):
            preferred = [category] if category not in ("Image", "Audio", "Document", "VersionInfo") else []
            for key in keys:
                for prefix in preferred:
                    for name, val in raw.items():
                        if name.split(":")[-1].casefold() == key.casefold() and name.startswith(prefix):
                            return val
                for name, val in raw.items():
                    if name.split(":")[-1].casefold() == key.casefold():
                        return val
            return ""

        if category == "BinarySign":
            value = lookup("FileTypeExtension") if field == "Extension" else lookup("FileType", "MIMEType")
            if field == "Extension":
                value = str(value).lower()
        elif field in {"WidthAndHeight", "AspectRatio", "Pixels"}:
            width, height = lookup("ImageWidth"), lookup("ImageHeight")
            value = ""
            if width and height:
                value = (
                    f"{width}x{height}"
                    if field == "WidthAndHeight"
                    else str(float(width) / float(height))
                    if field == "AspectRatio"
                    else str(int(width) * int(height))
                )
        elif field.startswith("Duration"):
            duration = lookup("Duration", "AudioDuration", "VideoDuration")
            value = ""
            if duration != "":
                seconds = float(duration)
                value = (
                    str(seconds / 60)
                    if field == "DurationMins"
                    else str(seconds)
                    if field == "DurationSecs"
                    else f"{int(seconds) // 3600:02}:{int(seconds) // 60 % 60:02}:{int(seconds) % 60:02}"
                )
        elif category == "Email":
            value = lookup(
                {
                    "Sender": "From",
                    "Recipient": "To",
                    "Recipients": "To",
                    "MessageID": "MessageID",
                    "SenderName": "SenderName",
                    "SenderEmail": "SenderEmailAddress",
                    "RecipientName": "RecipientName",
                    "RecipientEmail": "RecipientEmailAddress",
                }.get(field, field)
            )
        else:
            value = lookup(*CONTENT_KEYS.get(field, (field,)))
            if field == "Year" and value:
                value = str(value)[:4]
            if field == "Date" and value:
                text = str(value)
                text = text[:10].replace(":", "-") + text[10:]
                try:
                    value = format_date(datetime.fromisoformat(text), "yyyy-mm-dd hh-nn-ss")
                except ValueError:
                    value = ""
        result = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        values[tag] = result
        return result
