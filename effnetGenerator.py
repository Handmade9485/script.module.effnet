import random
import xbmc
import xbmcgui
import sqlite3
import xbmcaddon
import xbmcvfs
import os
import math
import json


# 0 = integer input
playlist_size = int(xbmcgui.Dialog().numeric(0, "Playlist Size", "50"))
start_song_path = xbmc.getInfoLabel("ListItem.Filenameandpath")
start_song_kodi_id = xbmc.getInfoLabel("ListItem.DBID")


xbmcgui.Dialog().notification("Playlist Generator", f"Starting from: {xbmc.getInfoLabel("ListItem.Title")}")

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
""", (start_song_effnet_id, int(playlist_size)))

closest_songs_ids = {start_song_effnet_id}
for song_a_id, song_b_id in cursor.fetchall():
    closest_songs_ids.add(song_a_id)
    closest_songs_ids.add(song_b_id)

xbmc.log(f"Closest song ids {closest_songs_ids}", xbmc.LOGDEBUG)

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

xbmc.log(f"Distances: {song_distance_graph}", xbmc.LOGDEBUG)
max_dist = sum(song_distance_graph.values()) / len(song_distance_graph) / 2
xbmc.log(f"Average distance: {max_dist * 2}", xbmc.LOGDEBUG)

unqueued = list(closest_songs_ids)
route = [start_song_effnet_id]
best_route = [start_song_effnet_id]
unqueued.remove(start_song_effnet_id)

# choose random song in the further half from the start
target_song = random.choice(sorted(unqueued, key=lambda s: song_distance_graph.get((start_song_effnet_id, s), 1))[len(unqueued)//2:])

def get_playlist_song_weight(s, current_song, progress):
    distance = song_distance_graph.get((current_song, s), 1) + \
               song_distance_graph.get((target_song, s), 1) * progress + \
               song_distance_graph.get((start_song_effnet_id, s), 1) * (1-progress)
    return 1 / distance

rebalancings = 1
def gen_route():
    global rebalancings
    global best_route
    if len(route) > len(best_route):
        best_route = route.copy()

    if len(route) >= playlist_size or not unqueued:
        return True

    current = route[-1]

    candidates = [s for s in unqueued if song_distance_graph.get((current, s), 1) < max_dist]
    if not candidates:
        return False

    progress = len(route) / playlist_size
    weights = [get_playlist_song_weight(s, current, progress) for s in candidates]
    # reduce number of choices over time or the function will run forever
    choices = random.choices(candidates, weights=weights, k=5 - int(math.log10(rebalancings) / 1.5))

    for choice in choices:
        route.append(choice)
        unqueued.remove(choice)
        if gen_route():
            return True
        else:
            xbmc.log(f"Rebalancing", xbmc.LOGDEBUG)
            route.pop()
            unqueued.append(choice)
    rebalancings += 1
    return False

gen_route()
route = best_route
xbmc.log(f"Final route: {route}", xbmc.LOGDEBUG)


placeholders = ",".join("?" * len(closest_songs_ids))
cursor.execute(f"SELECT id, path FROM songs WHERE id IN ({placeholders})", list(closest_songs_ids))
id_to_path = {row["id"]: row["path"] for row in cursor.fetchall()}
paths = [id_to_path[i] for i in route]

connection.close()

xbmc.executeJSONRPC(json.dumps({
    "jsonrpc": "2.0",
    "method": "Playlist.Clear",
    "params": {"playlistid": 0},
    "id": 1
}))
for song in paths:
    # xbmc.log(f"Adding song: {song}", xbmc.LOGDEBUG)
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

# debug zone
if len(route) > 1:
    def print_graph(distances, name):
        chars = "▁▂▃▄▅▆▇█"
        char_len = len(chars)

        mn = min(distances)
        mx = max(distances)

        if mx > mn:
            graph = "".join(
                chars[int((d - mn) / mx * (char_len-1))]
                for d in distances
            )
        else:
            graph = chars[0] * len(distances)

        xbmc.log(f"{name}: {mx:.5f}: {graph}", xbmc.LOGDEBUG)

    distances = [song_distance_graph.get((start_song_effnet_id, s), 1) for s in route[1:]]
    neighbors = [song_distance_graph.get((route[i], route[i+1]), 1) for i in range(len(route)-1)]

    xbmc.log(f"Target song: {id_to_path[target_song]}", xbmc.LOGDEBUG)
    print_graph(distances, "Distance trend")
    print_graph(neighbors, "Neighbor trend")
