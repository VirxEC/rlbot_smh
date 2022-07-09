import json
import multiprocessing as mp
import sys
from pathlib import Path
from traceback import print_exc

from rlbot.setup_manager import RocketLeagueLauncherPreference, SetupManager

from .showroom_util import (fetch_game_tick_packet, set_game_state,
                            spawn_car_for_viewing)
from .start_match_util import start_match_helper


def listen():
    mp.set_start_method("spawn")

    sm = SetupManager()
    
    try:
        online = True
        while online:
            command = sys.stdin.readline()
            print(command)
            params = command.split(" | ")

            if params[0] == "start_match":
                bot_list = json.loads(params[1])
                match_settings = json.loads(params[2])

                preferred_launcher = params[3]
                use_login_tricks = bool(params[4])
                if params[5] != "":
                    rocket_league_exe_path = Path(params[5])
                else:
                    rocket_league_exe_path = None

                start_match_helper(sm, bot_list, match_settings, RocketLeagueLauncherPreference(preferred_launcher, use_login_tricks, rocket_league_exe_path))
            elif params[0] == "shut_down":
                sm.shut_down(time_limit=5, kill_all_pids=True)
                online = False
            elif params[0] == "fetch-gtp":
                print(f"-|-*|GTP {json.dumps(fetch_game_tick_packet(sm))}|*-|-", flush=True)
            elif params[0] == "set_state":
                state = json.loads(params[1])
                set_game_state(state)
            elif params[0] == "spawn_car_for_viewing":
                config = json.loads(params[1])
                team = int(params[2])
                showcase_type = params[3]
                map_name = params[4]

                preferred_launcher = params[5]
                use_login_tricks = bool(params[6])
                if params[5] != "":
                    rocket_league_exe_path = Path(params[7])
                else:
                    rocket_league_exe_path = None

                spawn_car_for_viewing(sm, config, team, showcase_type, map_name, RocketLeagueLauncherPreference(preferred_launcher, use_login_tricks, rocket_league_exe_path))
    except Exception:
        print_exc()

    sm.shut_down(time_limit=5, kill_all_pids=True)

    print("Closing...", flush=True)
    exit()
