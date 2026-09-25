from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from typing import Any

_WS = b"\x00\t\n\x0c\r "
_DELIM = b"()<>[]{}/%"
_OBJ_RE = re.compile(rb"(\d+)[ \t]+(\d+)[ \t]+obj\b")


class PdfCosError(Exception):
    pass


@dataclass
class PdfStream:
    d: dict
    data: bytes


def _is_ref(obj: Any) -> bool:
    return isinstance(obj, tuple) and len(obj) == 3 and obj[0] == "R"


class PdfCos:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.n = len(data)
        self.offsets: dict[int, int] = {}
        self.objects: dict[int, Any] = {}
        self._parsing: set[int] = set()
        for match in _OBJ_RE.finditer(data):
            self.offsets[int(match.group(1))] = match.start()
        for num in list(self.offsets):
            self.get(num)
        self._expand_object_streams()

    def get(self, num: int) -> Any:
        if num in self.objects:
            return self.objects[num]
        if num in self._parsing or num not in self.offsets:
            return None
        self._parsing.add(num)
        try:
            parser = _Parser(self.data, self)
            parser.i = self.offsets[num]
            parser._skip()
            parser.parse_number()
            parser._skip()
            parser.parse_number()
            parser._skip()
            if not parser.data.startswith(b"obj", parser.i):
                return None
            parser.i += 3
            value = parser.parse_value()
            self.objects[num] = value
            return value
        except Exception:
            return None
        finally:
            self._parsing.discard(num)

    def resolve(self, obj: Any) -> Any:
        seen: set[int] = set()
        while _is_ref(obj):
            num = int(obj[1])
            if num in seen:
                return None
            seen.add(num)
            obj = self.get(num)
        return obj

    def catalog(self) -> dict:
        for num in sorted(self.objects, reverse=True):
            obj = self.resolve(self.get(num))
            d = obj.d if isinstance(obj, PdfStream) else obj
            if isinstance(d, dict) and d.get("/Type") == "/Catalog":
                return d
        return {}

    def pages(self) -> list[dict]:
        out: list[dict] = []

        def walk(node: Any) -> None:
            node = self.resolve(node)
            if isinstance(node, PdfStream):
                node = node.d
            if not isinstance(node, dict):
                return
            kids = self.resolve(node.get("/Kids"))
            if isinstance(kids, list) and kids:
                for kid in kids:
                    walk(kid)
                return
            out.append(node)

        walk(self.catalog().get("/Pages"))
        return out

    def page(self, index0: int) -> dict | None:
        pages = self.pages()
        if index0 < 0 or index0 >= len(pages):
            return None
        return pages[index0]

    def annots(self, page: dict) -> list[dict]:
        raw = self.resolve(page.get("/Annots")) or []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        for item in raw:
            annot = self.resolve(item)
            if isinstance(annot, dict):
                out.append(annot)
        return out

    def decode_stream(self, stream: PdfStream) -> bytes:
        data = stream.data
        filt = self.resolve(stream.d.get("/Filter"))
        parms = self.resolve(stream.d.get("/DecodeParms") or stream.d.get("/DP"))
        filters = filt if isinstance(filt, list) else ([filt] if filt else [])
        parms_list = parms if isinstance(parms, list) else ([parms] if parms else [])
        for i, name in enumerate(filters):
            name = name if isinstance(name, str) else ""
            extra = self.resolve(parms_list[i]) if i < len(parms_list) else {}
            if not isinstance(extra, dict):
                extra = {}
            if name in ("/FlateDecode", "/Fl"):
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    data = zlib.decompress(data, -15)
                data = _apply_predictor(data, extra)
            elif name in ("/ASCIIHexDecode", "/AHx"):
                data = _ascii_hex_decode(data)
            elif name in ("/ASCII85Decode", "/A85"):
                data = _ascii85_decode(data)
        return data

    def filespec(self, spec: Any) -> tuple[str, bytes]:
        spec = self.resolve(spec)
        if isinstance(spec, str):
            name = spec[1:] if spec.startswith("/") else spec
            return name, self.embedded_files().get(name, b"")
        if not isinstance(spec, dict):
            return "", b""
        name = _as_filename(spec.get("/UF") or spec.get("/F") or spec.get("/DOS") or "")
        blob = b""
        ef = self.resolve(spec.get("/EF"))
        if isinstance(ef, dict):
            for key in ("/F", "/UF", "/DOS", "/Mac", "/Unix"):
                stream = self.resolve(ef.get(key))
                if isinstance(stream, PdfStream):
                    blob = self.decode_stream(stream)
                    break
        if not blob and name:
            blob = self.embedded_files().get(name, b"")
        return name, blob

    def embedded_files(self) -> dict[str, bytes]:
        cached = getattr(self, "_embedded", None)
        if cached is not None:
            return cached
        names = self.resolve((self.catalog().get("/Names") or {}))
        tree = {}
        if isinstance(names, dict):
            tree = self._name_tree(names.get("/EmbeddedFiles"))
        out: dict[str, bytes] = {}
        for key, spec in tree.items():
            fname, blob = self.filespec(spec)
            out[fname or key] = blob
        self._embedded = out
        return out

    def _name_tree(self, node: Any) -> dict[str, Any]:
        node = self.resolve(node)
        if not isinstance(node, dict):
            return {}
        out: dict[str, Any] = {}
        names = self.resolve(node.get("/Names"))
        if isinstance(names, list):
            for i in range(0, len(names) - 1, 2):
                out[_as_filename(names[i])] = names[i + 1]
        kids = self.resolve(node.get("/Kids"))
        if isinstance(kids, list):
            for kid in kids:
                out.update(self._name_tree(kid))
        return out

    def _expand_object_streams(self) -> None:
        for obj in list(self.objects.values()):
            if not isinstance(obj, PdfStream):
                continue
            if obj.d.get("/Type") != "/ObjStm":
                continue
            try:
                n = int(self.resolve(obj.d.get("/N")) or 0)
                first = int(self.resolve(obj.d.get("/First")) or 0)
                payload = self.decode_stream(obj)
            except Exception:
                continue
            header = payload[:first]
            nums = [int(tok) for tok in header.split() if tok.isdigit()]
            pairs = list(zip(nums[0::2], nums[1::2]))[:n]
            for objnum, rel in pairs:
                if objnum in self.objects:
                    continue
                try:
                    parser = _Parser(payload, self)
                    parser.i = first + int(rel)
                    self.objects[int(objnum)] = parser.parse_value()
                except Exception:
                    continue


def _as_filename(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("latin-1", errors="ignore")
    text = str(value or "")
    if text.startswith("/"):
        text = text[1:]
    return text.strip()


def _apply_predictor(data: bytes, params: dict) -> bytes:
    predictor = int(params.get("/Predictor") or 1)
    if predictor <= 1:
        return data
    columns = int(params.get("/Columns") or 1)
    colors = int(params.get("/Colors") or 1)
    bpc = int(params.get("/BitsPerComponent") or 8)
    row = (columns * colors * bpc + 7) // 8
    if row <= 0:
        return data
    if predictor >= 10:
        out = bytearray()
        prev = bytes(row)
        i = 0
        while i + 1 + row <= len(data):
            tag = data[i]
            chunk = bytearray(data[i + 1 : i + 1 + row])
            i += 1 + row
            if tag == 1:
                for j in range(len(chunk)):
                    chunk[j] = (chunk[j] + (chunk[j - 1] if j else 0)) & 255
            elif tag == 2:
                for j in range(len(chunk)):
                    chunk[j] = (chunk[j] + prev[j]) & 255
            decoded = bytes(chunk)
            out.extend(decoded)
            prev = decoded
        return bytes(out)
    if predictor == 2:
        out = bytearray()
        for start in range(0, len(data), row):
            row_bytes = bytearray(data[start : start + row])
            for j in range(len(row_bytes)):
                if j >= colors:
                    row_bytes[j] = (row_bytes[j] + row_bytes[j - colors]) & 255
            out.extend(row_bytes)
        return bytes(out)
    return data


def _ascii_hex_decode(data: bytes) -> bytes:
    hexes = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
    if len(hexes) % 2:
        hexes += b"0"
    return bytes.fromhex(hexes.decode("ascii"))


def _ascii85_decode(data: bytes) -> bytes:
    data = re.sub(rb"\s+", b"", data)
    if data.startswith(b"<~"):
        data = data[2:]
    if data.endswith(b"~>"):
        data = data[:-2]
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i : i + 1] == b"z":
            out.extend(b"\x00\x00\x00\x00")
            i += 1
            continue
        chunk = data[i : i + 5]
        i += len(chunk)
        if not chunk:
            break
        pad = 5 - len(chunk)
        chunk = chunk + b"u" * pad
        acc = 0
        for ch in chunk:
            acc = acc * 85 + (ch - 33)
        out.extend(acc.to_bytes(4, "big")[: 4 - pad])
    return bytes(out)


class _Parser:
    def __init__(self, data: bytes, doc: PdfCos) -> None:
        self.data = data
        self.n = len(data)
        self.i = 0
        self.doc = doc

    def _skip(self) -> None:
        while self.i < self.n:
            ch = self.data[self.i : self.i + 1]
            if ch == b"%":
                while self.i < self.n and self.data[self.i] not in (10, 13):
                    self.i += 1
                continue
            if ch in _WS:
                self.i += 1
                continue
            break

    def _end_token(self, pos: int) -> bool:
        if pos >= self.n:
            return True
        ch = self.data[pos : pos + 1]
        return ch in _WS or ch in _DELIM

    def parse_value(self) -> Any:
        self._skip()
        if self.i >= self.n:
            raise PdfCosError("eof")
        b = self.data
        i = self.i
        if b.startswith(b"<<", i):
            return self.parse_dict_or_stream()
        if b[i : i + 1] == b"[":
            return self.parse_array()
        if b[i : i + 1] == b"(":
            return self.parse_literal()
        if b.startswith(b"<", i):
            return self.parse_hex()
        if b[i : i + 1] == b"/":
            return self.parse_name()
        if b.startswith(b"true", i) and self._end_token(i + 4):
            self.i = i + 4
            return True
        if b.startswith(b"false", i) and self._end_token(i + 5):
            self.i = i + 5
            return False
        if b.startswith(b"null", i) and self._end_token(i + 4):
            self.i = i + 4
            return None
        return self.parse_number_or_ref()

    def parse_name(self) -> str:
        self.i += 1
        out = bytearray()
        while self.i < self.n:
            ch = self.data[self.i : self.i + 1]
            if ch in _WS or ch in _DELIM:
                break
            self.i += 1
            if ch == b"#" and self.i + 1 < self.n:
                out.append(int(self.data[self.i : self.i + 2], 16))
                self.i += 2
            else:
                out.extend(ch)
        return "/" + out.decode("latin-1", errors="ignore")

    def parse_literal(self) -> str:
        self.i += 1
        depth = 1
        out = bytearray()
        while self.i < self.n and depth:
            ch = self.data[self.i]
            self.i += 1
            if ch == 92:
                if self.i >= self.n:
                    break
                nxt = self.data[self.i]
                self.i += 1
                mapping = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12, 40: 40, 41: 41, 92: 92}
                if nxt in mapping:
                    out.append(mapping[nxt])
                elif 48 <= nxt <= 57:
                    octs = [nxt]
                    while len(octs) < 3 and self.i < self.n and 48 <= self.data[self.i] <= 57:
                        octs.append(self.data[self.i])
                        self.i += 1
                    out.append(int(bytes(octs), 8) & 255)
                elif nxt in (10, 13):
                    if nxt == 13 and self.i < self.n and self.data[self.i] == 10:
                        self.i += 1
                else:
                    out.append(nxt)
            elif ch == 40:
                depth += 1
                out.append(ch)
            elif ch == 41:
                depth -= 1
                if depth:
                    out.append(ch)
            else:
                out.append(ch)
        if out.startswith(b"\xfe\xff"):
            return out[2:].decode("utf-16-be", errors="ignore")
        if out.startswith(b"\xff\xfe"):
            return out[2:].decode("utf-16-le", errors="ignore")
        try:
            return out.decode("utf-8")
        except UnicodeDecodeError:
            return out.decode("latin-1", errors="ignore")

    def parse_hex(self) -> str:
        self.i += 1
        start = self.i
        while self.i < self.n and self.data[self.i : self.i + 1] != b">":
            self.i += 1
        blob = _ascii_hex_decode(self.data[start : self.i])
        if self.i < self.n:
            self.i += 1
        return blob.decode("latin-1", errors="ignore")

    def parse_array(self) -> list:
        self.i += 1
        out: list[Any] = []
        while True:
            self._skip()
            if self.i >= self.n:
                break
            if self.data[self.i : self.i + 1] == b"]":
                self.i += 1
                break
            out.append(self.parse_value())
        return out

    def parse_dict_or_stream(self) -> Any:
        self.i += 2
        d: dict[str, Any] = {}
        while True:
            self._skip()
            if self.data.startswith(b">>", self.i):
                self.i += 2
                break
            key = self.parse_value()
            value = self.parse_value()
            if isinstance(key, str):
                d[key] = value
        self._skip()
        if not self.data.startswith(b"stream", self.i):
            return d
        self.i += 6
        if self.data.startswith(b"\r\n", self.i):
            self.i += 2
        elif self.data[self.i : self.i + 1] in (b"\n", b"\r"):
            self.i += 1
        length = self._length(d.get("/Length"))
        data = self.data[self.i : self.i + length]
        self.i += length
        self._skip()
        if self.data.startswith(b"endstream", self.i):
            self.i += 9
        return PdfStream(d, data)

    def _length(self, value: Any) -> int:
        value = self.doc.resolve(value) if _is_ref(value) else value
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def parse_number(self) -> int | float:
        self._skip()
        m = re.match(rb"[+\-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+\-]?\d+)?", self.data[self.i :])
        if not m:
            raise PdfCosError("number")
        tok = m.group(0)
        self.i += len(tok)
        if b"." in tok or b"e" in tok or b"E" in tok:
            return float(tok)
        return int(tok)

    def parse_number_or_ref(self) -> Any:
        n1 = self.parse_number()
        saved = self.i
        self._skip()
        if self.i < self.n and (self.data[self.i : self.i + 1] in b"+-." or 48 <= self.data[self.i] <= 57):
            n2 = self.parse_number()
            self._skip()
            if self.data.startswith(b"R", self.i) and self._end_token(self.i + 1):
                self.i += 1
                return ("R", int(n1), int(n2))
            self.i = saved
            return n1
        self.i = saved
        return n1
