import json
import multiprocessing as mp
import sys
from pathlib import Path
from threading import Thread
from traceback import print_exc
from typing import List

from rlbot.matchconfig.match_config import Team
from rlbot.setup_manager import RocketLeagueLauncherPreference, SetupManager

from .showroom_util import (fetch_game_tick_packet, set_game_state,
                            spawn_car_for_viewing)
from .start_match_util import create_match_config, start_match_helper
from .story_mode_util import add_match_result, run_challenge


def start_match(params: List[str], sm: SetupManager, out: mp.Queue):
    bot_list = json.loads(params[1])
    match_settings = json.loads(params[2])

    preferred_launcher = params[3]
    use_login_tricks = bool(params[4])
    if params[5] != "":
        rocket_league_exe_path = Path(params[5])
    else:
        rocket_league_exe_path = None

    start_match_helper(sm, bot_list, match_settings, RocketLeagueLauncherPreference(preferred_launcher, use_login_tricks, rocket_league_exe_path), out)


def stop_match(sm: SetupManager):
    if sm.has_started:
        sm.shut_down(kill_all_pids=True)


def fetch_gtp(sm: SetupManager):
    print(f"-|-*|GTP {json.dumps(fetch_game_tick_packet(sm))}|*-|-", flush=True)


def set_state(params: List[str], sm: SetupManager):
    state = json.loads(params[1])
    set_game_state(sm, state)


def spawn_view_car(params: List[str], sm: SetupManager):
    config = json.loads(params[1])
    team = int(params[2])
    showcase_type = params[3]
    map_name = params[4]

    preferred_launcher = params[5]
    use_login_tricks = bool(params[6])
    if params[7] != "":
        rocket_league_exe_path = Path(params[7])
    else:
        rocket_league_exe_path = None

    spawn_car_for_viewing(sm, config, team, showcase_type, map_name, RocketLeagueLauncherPreference(preferred_launcher, use_login_tricks, rocket_league_exe_path))


def launch_challenge(params: List[str], sm: SetupManager, out: mp.Queue):
    challenge_id = params[1]
    city_color = json.loads(params[2])
    team_color = json.loads(params[3])
    upgrades = json.loads(params[4])
    bot_list = json.loads(params[5])
    match_settings = json.loads(params[6])
    challenge = json.loads(params[7])
    save_state = json.loads(params[8])

    preferred_launcher = params[9]
    use_login_tricks = bool(params[10])
    if params[11] != "":
        rocket_league_exe_path = Path(params[11])
    else:
        rocket_league_exe_path = None

    match_config = create_match_config(bot_list, match_settings)

    for config in match_config.player_configs:
        if config.bot:
            # set the team colors
            if config.team == Team.BLUE:
                config.loadout_config.custom_color_id = team_color
            elif city_color is not None:
                config.loadout_config.team_color_id = city_color

    completed, results = run_challenge(sm, match_config, challenge, upgrades, RocketLeagueLauncherPreference(preferred_launcher, use_login_tricks, rocket_league_exe_path), out)

    save_state = add_match_result(save_state, challenge_id, completed, results)

    print(f"-|-*|STORY_RESULT {json.dumps(save_state)}|*-|-", flush=True)


def match_handler(q: mp.Queue, out: mp.Queue):
    sm = SetupManager()
    online = True

    while online:
        command = q.get()
        print(f"Received command: {command}")
        params = command.split(" | ")
        if len(params) == 0:
            continue

        try:
            if params[0] == "start_match":
                Thread(target=start_match, args=(params, sm, out)).start()
            elif params[0] == "kill_bots":
                stop_match(sm)
                out.put("done")
            elif params[0] == "shut_down":
                print("Got shut down signal")
                online = False
                out.put("shut_down")
            elif params[0] == "fetch_gtp":
                Thread(target=fetch_gtp, args=(sm,)).start()
            elif params[0] == "set_state":
                Thread(target=set_state, args=(params, sm)).start()
                out.put("done")
            elif params[0] == "spawn_car_for_viewing":
                Thread(target=spawn_view_car, args=(params, sm)).start()
                out.put("done")
            elif params[0] == "launch_challenge":
                Thread(target=launch_challenge, args=(params, sm, out)).start()
        except Exception:
            print_exc()
    stop_match(sm)


def listen():
    stdin_queue = mp.Queue()
    out_queue = mp.Queue()
    match_handler_thread = mp.Process(target=match_handler, args=(stdin_queue, out_queue), daemon=True)
    match_handler_thread.start()

    online = True
    while online:
        try:
            line = str(sys.stdin.readline())
            stdin_queue.put(line)
            if out_queue.get() == "shut_down":
                online = False
        except Exception:
            stdin_queue.put("shut_down | ")
            online = False

    print("Closing...")
    match_handler_thread.join(timeout=60)
    if match_handler_thread.is_alive():
        print("Match handler thread is still alive after 60 seconds, killing it")
        match_handler_thread.terminate()

    exit()
