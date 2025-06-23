from pathlib import Path
from typing import Generator, BinaryIO
from playlist import Playlist, Track, PlaylistReader
import struct
from urllib.parse import unquote
from Cryptodome.Cipher import AES
import zlib
from io import BytesIO

class AppleMusicLibraryDecryptor:
    def __init__(self, key: str, library: Path):
        self.key = key
        self.library = library

    def decrypt(self, debug=False) -> BinaryIO:
        with self.library.open("rb") as inf:
            assert inf.read(4) == bytes('hfma', 'ascii')
            envelope_length, file_size = struct.unpack('<II', inf.read(8))
            inf.seek(84)
            max_crypt_size = struct.unpack('<I', inf.read(4))[0]

            if max_crypt_size < file_size:
                crypt_size = max_crypt_size
            else:
                crypt_size = file_size - envelope_length - ((file_size - envelope_length) % 16)

            if debug:
                print(f'envelope_length: {envelope_length}')
                print(f'file_size: {file_size}')
                print(f'max_crypt_size: {max_crypt_size}')
                print(f'crypt_size: {crypt_size}')

            inf.seek(0)
            out_data = inf.read(envelope_length)

            cipher = AES.new(self.key, AES.MODE_ECB)
            decrypted = cipher.decrypt(inf.read(crypt_size))
            compressed_data = decrypted + inf.read()

            out_data += zlib.decompress(compressed_data)

        return BytesIO(out_data)

class AppleMusicReader(PlaylistReader):
    def __init__(self, chunks: 'list[Section]'):
        self.chunks = chunks

        self._parse_tracks()

    def _parse_tracks(self):
        chunk_iter = iter(self.chunks)
        while True:
            curr = next(chunk_iter)
            if isinstance(curr, HSMA) and curr.subtype == 1:
                break

        ltma = next(chunk_iter)
        assert isinstance(ltma, LTMA)

        self.tracks = {}

        track_id = None
        curr_track = None

        def finalize_track():
            if track_id is not None:
                if curr_track.album_artist is None:
                    curr_track.album_artist = curr_track.track_artist
                self.tracks[track_id] = curr_track

        while True:
            curr = next(chunk_iter)
            if isinstance(curr, HSMA):
                finalize_track()
                break
            elif isinstance(curr, ITMA):
                finalize_track()
                track_id = curr.track_id
                curr_track = Track(None, None, None, None, None, None)
            elif isinstance(curr, BOMA_TrackNumerics):
                curr_track.duration = curr.duration_ms
            elif isinstance(curr, BOMA_URI):
                assert curr.uri.startswith('file://localhost/')
                curr_track.location = Path(unquote(curr.uri[len('file://localhost/'):]))
            elif isinstance(curr, BOMA_String):
                match(curr.subtype):
                    case 0x02:
                        curr_track.track_name = curr.value
                    case 0x04:
                        curr_track.track_artist = curr.value
                    case 0x03:
                        curr_track.album_name = curr.value
                    case 0x1B:
                        curr_track.album_artist = curr.value
        assert len(self.tracks) == ltma.itma_count, f'unexpected number of tracks parsed ({len(self.tracks)} != {ltma.itma_count})'

    def read_track(self, id: str) -> Track:
        if id not in self.tracks:
            raise ValueError(f'Unknown id "{id}"')

        return self.tracks[id]

    def read_playlists(self) -> Generator[Playlist, None, None]:
        chunk_iter = iter(self.chunks)
        while True:
            curr = next(chunk_iter)
            if isinstance(curr, HSMA) and curr.subtype == 2:
                break

        lpma_master = next(chunk_iter)
        assert isinstance(lpma_master, LPMA_Master)

        curr_lpma: LPMA = None
        curr_title: str = None
        curr_tracks = []

        playlist_count = 0

        while True:
            try:
                curr = next(chunk_iter)
            except StopIteration:
                break

            if isinstance(curr, HSMA):
                break
            elif isinstance(curr, LPMA):
                if curr_lpma is not None:
                    assert curr_title is not None
                    assert len(curr_tracks) == curr_lpma.track_count, f'Warning: mismatch track count for playlist "{curr_title}", ({len(curr_tracks)} != {curr_lpma.track_count})'
                    playlist_count += 1
                    yield Playlist(curr_title, [self.read_track(id) for id in curr_tracks])
                curr_lpma = curr
                curr_tracks = []
                curr_title = None
            elif isinstance(curr, BOMA_String):
                assert curr.subtype == 0xC8, f"Found BOMA_String of unexpected type '{BOMA_String.STRING_TYPES.get(curr.subtype, hex(curr.subtype))}'"
                curr_title = curr.value
            elif isinstance(curr, BOMA_PlaylistTrack):
                curr_tracks.append(curr.track_id)

        if curr_lpma is not None:
            assert curr_title is not None
            assert len(curr_tracks) == curr_lpma.track_count, f'Warning: mismatch track count for playlist "{curr_title}", ({len(curr_tracks)} != {curr_lpma.track_count})'
            playlist_count += 1
            yield Playlist(curr_title, [self.read_track(id) for id in curr_tracks])

        assert playlist_count == lpma_master.lpma_count

    @staticmethod
    def load_file(file: BinaryIO) -> 'AppleMusicReader':
        chunks = []
        while True:
            offset = file.tell()
            signature = file.read(4)
            if len(signature) != 4:
                break
            try:
                decoded = signature.decode('ascii')
            except UnicodeDecodeError:
                break
            match decoded:
                case 'hsma':
                    chunks.append(HSMA.read_section(offset, file))
                case 'boma':
                    chunks.append(BOMA.read_section(offset, file))
                case 'ltma':
                    chunks.append(LTMA.read_section(offset, file))
                case 'itma':
                    chunks.append(ITMA.read_section(offset, file))
                case 'lPma':
                    chunks.append(LPMA_Master.read_section(offset, file))
                case 'lpma':
                    chunks.append(LPMA.read_section(offset, file))
                case 'hfma' | 'plma' | 'lama' | 'iama' | 'lAma' | 'iAma':
                    chunks.append(Section.read_section(decoded, offset, file))
                case _:
                    break
        return AppleMusicReader(chunks)

class Section:
    def __init__(self, signature: str, offset: int, section_length: int, data: bytes):
        self.signature = signature
        self.offset = offset
        self.section_length = section_length
        self.data = data

    def __str__(self):
        return f'Section(signature={self.signature}, offset=0x{self.offset:x}, length=0x{self.section_length:x})'

    @staticmethod
    def read_section(signature: str, offset: int, file: BinaryIO) -> 'Section':
        section_length, = struct.unpack('<I', file.read(4))
        data = file.read(section_length - 8)
        return Section(signature, offset, section_length, data)

class BOMA(Section):
    def __init__(self, offset: int, section_length: int, data: bytes, subtype: int):
        super().__init__('boma', offset, section_length, data)
        self.subtype = subtype

    @staticmethod
    def read_section(offset: int, file: BinaryIO) -> 'BOMA':
        constant, section_length, subtype = struct.unpack('<III', file.read(12))
        data = file.read(section_length - 16)

        if subtype in BOMA_String.STRING_TYPES:
            return BOMA_String.parse_section(offset, section_length, data, subtype)

        match subtype:
            case 0x01:
                return BOMA_TrackNumerics.parse_section(offset, section_length, data)
            case 0x0B:
                return BOMA_URI.parse_section(offset, section_length, data)
            case 0xCE:
                return BOMA_PlaylistTrack.parse_section(offset, section_length, data)
            case _:
                return BOMA(offset, section_length, data, subtype)

    def __str__(self):
        return f'BOMA(offset=0x{self.offset:x}, length=0x{self.section_length:x}, subtype="{hex(self.subtype)}")'

class BOMA_String(BOMA):
    STRING_TYPES = {
        0x0002: 'Track Title',
        0x0003: 'Album',
        0x0004: 'Artist',
        0x0005: 'Genre',
        0x0006: 'Kind',
        0x0007: '(not sure)',
        0x0008: 'Comment',
        0x000C: 'Composer',
        0x000E: 'Grouping (Classical)',
        0x0012: 'Episode Comment (maybe)',
        0x0016: 'Episode Synopsis',
        0x0018: 'Series Title',
        0x0019: 'Episode Number',
        0x001B: 'Album Artist',
        0x001C: 'Series (Unknown Info)',
        0x001E: 'Sort Order Track Name',
        0x001F: 'Sort Order Album',
        0x0020: 'Sort Order Artist',
        0x0021: 'Sort Order Album Artist',
        0x0022: 'Sort Order Composer',
        0x002B: 'Licensor/Copyright Holder ?',
        0x002E: '(not sure)',
        0x0033: 'Series Synopsis',
        0x0034: 'Flavor String',
        0x003B: 'Email (purchaser?)',
        0x003C: 'Name (purchaser?)',
        0x003F: 'Work Name (for Classical Tracks)',
        0x0040: 'Movement Name (for Classical Tracks)',
        0x00C8: 'Playlist Name',
        0x012C: 'iama Album',
        0x012D: 'iama Album Artist',
        0x012E: 'iama Album Artist',
        0x012F: 'Series Title',
        0x01F4: 'Unknown 64x4b Hex String',
        0x01F8: 'Managed Media Folder',
        0x01FE: 'Unknown 64x4b Hex String',
        0x02BE: 'Song Title (Application.musicdb)',
        0x02BF: 'Song Artist (Application.musicdb)',
    }

    def __init__(self, offset: int, section_length: int, data: bytes, subtype: int, value: str):
        super().__init__(offset, section_length, data, subtype)
        self.value = value

    @staticmethod
    def parse_section(offset: int, section_length: int, data: bytes, subtype: int):
        bytelength,  = struct.unpack('<I', data[8:12])
        str_bytes = data[20:bytelength+20]
        value = str_bytes.decode('utf-16')
        return BOMA_String(offset, section_length, data, subtype, value)

    def __str__(self):
        return f'BOMA_String(offset=0x{self.offset:x}, length=0x{self.section_length:x}, label="{BOMA_String.STRING_TYPES[self.subtype]}", value="{self.value}")'

class BOMA_PlaylistTrack(BOMA):
    def __init__(self, offset: int, section_length: int, data: bytes, track_id: str):
        super().__init__(offset, section_length, data, 0xCE)
        self.track_id = track_id

    @staticmethod
    def parse_section(offset: int, section_length: int, data: bytes):
        assert data[4:8] == 'ipfa'.encode('ascii')

        track_id  = ''.join(f'{d:X}' for d in data[24:32])
        return BOMA_PlaylistTrack(offset, section_length, data, track_id)

    def __str__(self):
        return f'BOMA_PlaylistTrack(offset=0x{self.offset:x}, length=0x{self.section_length:x}, track_id="{self.track_id}")'

class BOMA_URI(BOMA):
    def __init__(self, offset: int, section_length: int, data: bytes, uri: str):
        super().__init__(offset, section_length, data, 0x0B)
        self.uri = uri

    @staticmethod
    def parse_section(offset: int, section_length: int, data: bytes):
        uri_length, = struct.unpack('<I', data[8:12])
        uri = data[20:uri_length+20].decode('utf-8')
        return BOMA_URI(offset, section_length, data, uri)

    def __str__(self):
        return f'BOMA_URI(offset=0x{self.offset:x}, length=0x{self.section_length:x}, uri="{self.uri}")'

class BOMA_TrackNumerics(BOMA):
    def __init__(self, offset: int, section_length: int, data: bytes, duration_ms: int):
        super().__init__(offset, section_length, data, 0x01)
        self.duration_ms = duration_ms

    @staticmethod
    def parse_section(offset: int, section_length: int, data: bytes):
        duration_ms, = struct.unpack('<I', data[160:164])
        return BOMA_TrackNumerics(offset, section_length, data, duration_ms)

    def __str__(self):
        return f'BOMA_TrackNumerics(offset=0x{self.offset:x}, length=0x{self.section_length:x}, duration_ms="{self.duration_ms}")'

class HSMA(Section):
    def __init__(self, offset: int, section_length: int, data: bytes, associated_length: int, subtype: int):
        super().__init__('hsma', offset, section_length, data)
        self.associated_length = associated_length
        self.subtype = subtype

    @staticmethod
    def read_section(offset, file):
        section = Section.read_section('hsma', offset, file)
        associated_length, subtype = struct.unpack('<II', section.data[:8])
        return HSMA(section.offset, section.section_length, section.data, associated_length, subtype)

    def __str__(self):
        subtypes = {
            1: 'Holds Track Master (ltma) and associated data',
            2: 'Playlist data',
            3: 'Holds Playlist Master (lPma) and associated data or inner hfma',
            4: 'Holds lama and associated data.',
            5: 'Holds lAma and associated data.',
            6: 'Holds Library Master (plma) and associated (boma) data.',
        }
        return f'HSMA(offset=0x{self.offset:x}, length=0x{self.section_length:x}, associated_length=0x{self.associated_length}, subtype="{subtypes.get(self.subtype, hex(self.subtype))}")'

class LTMA(Section):
    def __init__(self, offset: int, section_length: int, data: bytes, itma_count: int):
        super().__init__('ltma', offset, section_length, data)
        self.itma_count = itma_count

    @staticmethod
    def read_section(offset, file):
        section = Section.read_section('ltma', offset, file)
        itma_count, = struct.unpack('<I', section.data[:4])
        return LTMA(section.offset, section.section_length, section.data, itma_count)

    def __str__(self):
        return f'LTMA(offset=0x{self.offset:x}, length=0x{self.section_length:x}, itma_count:{self.itma_count})'

class ITMA(Section):
    def __init__(self, offset: int, section_length: int, data: bytes, track_id: str, track_no: int):
        super().__init__('itma', offset, section_length, data)
        self.track_id = track_id
        self.track_no = track_no

    @staticmethod
    def read_section(offset, file):
        section = Section.read_section('itma', offset, file)
        track_id = ''.join(f'{d:X}' for d in section.data[8:16])
        track_no, = struct.unpack('<H', section.data[152:154])
        return ITMA(section.offset, section.section_length, section.data, track_id, track_no)

    def __str__(self):
        return f'ITMA(offset=0x{self.offset:x}, length=0x{self.section_length:x}, track_id="{self.track_id}", track_no={self.track_no})'

class LPMA_Master(Section):
    def __init__(self, offset: int, section_length: int, data: bytes, lpma_count: int):
        super().__init__('lPma', offset, section_length, data)
        self.lpma_count = lpma_count

    @staticmethod
    def read_section(offset, file):
        section = Section.read_section('lPma', offset, file)
        lpma_count, = struct.unpack('<I', section.data[0:4])
        return LPMA_Master(section.offset, section.section_length, section.data, lpma_count)

    def __str__(self):
        return f'LPMA_Master(offset=0x{self.offset:x}, length=0x{self.section_length:x}, lpma_count={self.lpma_count})'

class LPMA(Section):
    def __init__(self, offset: int, section_length: int, data: bytes, track_count: int):
        super().__init__('lpma', offset, section_length, data)
        self.track_count = track_count

    @staticmethod
    def read_section(offset, file):
        section = Section.read_section('lpma', offset, file)
        track_count, = struct.unpack('<I', section.data[8:12])
        return LPMA(section.offset, section.section_length, section.data, track_count)

    def __str__(self):
        return f'LPMA(offset=0x{self.offset:x}, length=0x{self.section_length:x}, track_count={self.track_count})'


if __name__ == '__main__':
    scriptdir = Path(__file__).parent
    infile = scriptdir / 'Library.musicdb'
    assert infile.is_file()

    keyfile = scriptdir / 'itunes-key.txt'
    assert keyfile.exists(), f"Missing keyfile at {keyfile}"

    decrypted = scriptdir / 'Library.musicdb.bin'
    if decrypted.is_file():
        decrypted.unlink()

    chunks = scriptdir / 'DEBUG_chunks.txt'
    tracks = scriptdir / 'DEBUG_tracks.txt'
    playlists = scriptdir / 'DEBUG_playlists.txt'

    with keyfile.open('r') as inf:
        key = inf.read().strip()
        key = key.encode('ascii')

    with decrypted.open('wb') as outf:
        outf.write(AppleMusicLibraryDecryptor(key, infile).decrypt(True).read())

    with decrypted.open('rb') as inf:
        reader = AppleMusicReader.load_file(inf)

    with chunks.open('w', encoding='utf-8') as outf:
        for chunk in reader.chunks:
            print(chunk, file=outf)

    with tracks.open('w', encoding='utf-8') as outf:
        for id, track in reader.tracks.items():
            print(f'{id} - {str(track)}', file=outf)

    with playlists.open('w', encoding='utf-8') as outf:
        for plist in reader.read_playlists():
            print(plist, file=outf)
            print(file=outf)
