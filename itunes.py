from pathlib import Path
import plistlib
from typing import Generator
from playlist import Playlist, Track
from urllib.parse import unquote

class iTunesReader:
    def __init__(self, library: Path):
        with library.open('rb') as inf:
            self.library = plistlib.load(inf, fmt=plistlib.FMT_XML)
        
        self.track_cache: 'dict[int, Track]' = {}
    
    def read_track(self, id: int) -> Track:
        if id in self.track_cache:
            return self.track_cache[id]
        
        if str(id) not in self.library['Tracks']:
            raise ValueError(f'Invalid track id {id}')
        
        track = self.library['Tracks'][str(id)]
        location = track['Location']
        assert location.startswith('file://localhost/')
        location = Path(unquote(location[len('file://localhost/'):]))

        assert location.is_file(), f"File not found: {location}"

        return Track(
            track['Name'],
            track['Artist'],
            track['Album'],
            track['Album Artist'],
            location,
            track['Total Time']
        )
    
    def _parse_playlist(self, data):
        tracks = [self.read_track(item['Track ID']) for item in data['Playlist Items']]
        return Playlist(data['Name'], tracks)

    def read_playlists(self) -> Generator[Playlist, None, None]:
        for playlist in self.library['Playlists']:
            try:
                yield self._parse_playlist(playlist)
            except (ValueError, AssertionError, KeyError) as e:
                # print(f'Skipping {playlist['Name']} due to {repr(e)}')
                pass 
