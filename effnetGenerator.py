import xbmc
import xbmcgui
import sqlite3
import xbmcaddon
import xbmcvfs
import os
import math
import json


start_song_path = xbmc.getInfoLabel("ListItem.Filenameandpath")
start_song_kodi_id = xbmc.getInfoLabel("ListItem.DBID")

xbmcgui.Dialog().notification("Playlist Generator", f"Starting from:\n{xbmc.getInfoLabel("ListItem.Title")}")

addon = xbmcaddon.Addon()
addon_path = xbmcvfs.translatePath(addon.getAddonInfo("path"))
db_dir = os.path.join(addon_path, "resources")
db_path = os.path.join(db_dir, "effnet.db")

connection = sqlite3.connect(db_path)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()


cursor.execute("SELECT id FROM songs WHERE path = ?", (start_song_path,))
start_song_effnet_id = cursor.fetchone()["id"]

if not start_song_effnet_id:
    xbmcgui.Dialog().ok("Error", "Selected song not found in analysis database.")
    raise SystemExit

xbmc.log(f"Starting song id {start_song_effnet_id}", xbmc.LOGINFO)

cursor.execute("""
    SELECT song_a_id, song_b_id
    FROM song_distances
    WHERE ? in (song_a_id, song_b_id)
    ORDER BY distance ASC
    LIMIT ?
""", (start_song_effnet_id, 50))

closest_songs_ids = {start_song_effnet_id}
for song_a_id, song_b_id in cursor.fetchall():
    closest_songs_ids.add(song_a_id)
    closest_songs_ids.add(song_b_id)

xbmc.log(f"Closest song ids {closest_songs_ids}", xbmc.LOGINFO)

placeholders = ",".join("?" * len(closest_songs_ids))
cursor.execute(f"""
    SELECT song_a_id, song_b_id, distance
    FROM song_distances
    WHERE song_a_id in ({placeholders}) and song_b_id in ({placeholders})
""", list(closest_songs_ids) + list(closest_songs_ids))

song_distance_graph = dict()
for song_a_id, song_b_id, distance in cursor.fetchall():
    song_distance_graph[(song_a_id, song_b_id)] = distance
    song_distance_graph[(song_b_id, song_a_id)] = distance

xbmc.log(f"Distances: {song_distance_graph}", xbmc.LOGINFO)

route = [start_song_effnet_id]
current_song = start_song_effnet_id
closest_songs_ids.remove(start_song_effnet_id)

while closest_songs_ids:
    best = min(closest_songs_ids, key=lambda s: song_distance_graph.get((current_song, s), 1))
    route.append(best)
    closest_songs_ids.remove(best)
    current_song = best

xbmc.log(f"Initial route: {route}", xbmc.LOGINFO)

def total_cost(route):
    total = 0
    for i in range(len(route) - 1):
        a = route[i]
        b = route[i + 1]
        total += song_distance_graph.get((a, b), 1)
    return total

improved = True
while improved:
    improved = False
    for i in range(1, len(route) - 2):
        for j in range(i + 1, len(route)):
            # reverse songs from i to j
            new_route = (route[:i] + route[i:j][::-1] + route[j:])
            if total_cost(new_route) < total_cost(route):
                route = new_route
                improved = True

xbmc.log(f"Final route: {route}", xbmc.LOGINFO)


def id_to_path(route):
    placeholders = ",".join("?" * len(route))
    cursor.execute(f"SELECT id, path FROM songs WHERE id IN ({placeholders})", route)
    id_to_path = {row["id"]: row["path"] for row in cursor.fetchall()}
    return [id_to_path[i] for i in route]


paths = id_to_path(route)
connection.close()

xbmc.executeJSONRPC(json.dumps({
    "jsonrpc": "2.0",
    "method": "Playlist.Clear",
    "params": {"playlistid": 0},
    "id": 1
}))
for song in paths:
    xbmc.executeJSONRPC(json.dumps({
        "jsonrpc": "2.0",
        "method": "Playlist.Add",
        "params": {
            "playlistid": 0,
            "item": {"file": song}
        },
        "id": 1
    }))
xbmc.executeJSONRPC(json.dumps({
    "jsonrpc": "2.0",
    "method": "Player.Open",
    "params": {
        "item": {"playlistid": 0, "position": 0}
    },
    "id": 1
}))


xbmcgui.Dialog().notification("Playlist Generator", f"Loaded {len(route)} similar songs.")
