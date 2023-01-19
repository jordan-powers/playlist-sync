from pathlib import Path
import plistlib
import json
import functools
from urllib.parse import unquote

settings_path = Path(__file__).parent / 'settings.json'
with settings_path.open("r") as inf:
    settings = json.load(inf)

itunes_lib_path = Path(settings['iTunes Library Path'])
groove_playlist_path = Path(settings['Groove Playlist Directory'])
playlist_names = [plist.lower() for plist in settings['Playlists']]

if not itunes_lib_path.is_file():
    print("Could not find iTunes library!")
    exit(1)

if not groove_playlist_path.is_dir():
    print("Invalid Groove playlist directory!")
    exit(1)

with itunes_lib_path.open("rb") as inf:
    itunes_library = plistlib.load(inf, fmt=plistlib.FMT_XML)

class Track:
    def __init__(self, track_name: str, track_artist: str, album_name: str, album_artist: str, location: Path, duration: int):
        self.track_name = track_name
        self.track_artist = track_artist
        self.album_name = album_name
        self.album_artist = album_artist
        self.location = location
        self.duration = duration

    @staticmethod
    @functools.cache
    def from_itunes(id: int) -> 'Track':
        if str(id) not in itunes_library['Tracks']:
            raise ValueError(f'Invalid track id {id}')

        track = itunes_library['Tracks'][str(id)]
        location = track['Location']
        assert location.startswith('file://localhost/')
        location = Path(unquote(location[len('file://localhost/'):]))
        assert location.is_file()

        return Track(
            track['Name'],
            track['Artist'],
            track['Album'],
            track['Album Artist'],
            location,
            track['Total Time']
        )

    def __str__(self) -> str:
        return f"{self.album_artist} - {self.album_name} - {self.track_name} - {str(self.location)}"

class Playlist:
    def __init__(self, name: str, tracks: 'list[Track]'):
        self.name = name
        self.tracks = tracks

    @staticmethod
    def from_itunes(data: dict) -> 'Playlist':
        tracks = [Track.from_itunes(item['Track ID']) for item in data['Playlist Items']]
        return Playlist(data['Name'], tracks)

    def __str__(self) -> str:
        out = f"Playlist - {self.name}:\n"
        for track in self.tracks:
            out += '  ' + str(track) + '\n'

        return out

parsed_playlists: 'list[Playlist]' = []

for playlist in itunes_library['Playlists']:
    if playlist['Name'].lower() in playlist_names:
        parsed_playlists.append(Playlist.from_itunes(playlist))


zpl_template = """
<?zpl version="2.0"?>
<smil>
  <head>
    <meta name="generator" content="Entertainment Platform -- 10.22031.1009.0" />
    <meta name="itemCount" content="{item_count}" />
    <meta name="totalDuration" content="{total_duration_ms}" />
    <title>{title}</title>
  </head>
  <body>
    <seq>
{items}
    </seq>
  </body>
</smil>
""".lstrip()

zpl_item_template = '      <media src="{src}" albumTitle="{album_title}" albumArtist="{album_artist}" trackTitle="{track_title}" trackArtist="{track_artist}" duration="{duration}" />'

for plist in parsed_playlists:
    zpl_items = []
    total_duration = 0
    for track in plist.tracks:
        total_duration += track.duration
        zpl_items.append(zpl_item_template.format(
            src=str(track.location),
            album_title=track.album_name,
            album_artist=track.album_artist,
            track_title=track.track_name,
            track_artist=track.track_artist,
            duration=track.duration
        ))

    zpl_playlist = zpl_template.format(
        item_count=len(plist.tracks),
        total_duration_ms=total_duration,
        title=plist.name,
        items='\n'.join(zpl_items)
    )

    zpl_out_path = groove_playlist_path / (plist.name + ".zpl")
    with zpl_out_path.open("w") as outf:
        outf.write(zpl_playlist)


