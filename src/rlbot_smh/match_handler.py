import json
import multiprocessing as mp
import sys
from pathlib import Path
from traceback import print_exc

from rlbot.matchconfig.match_config import Team
from rlbot.setup_manager import RocketLeagueLauncherPreference, SetupManager

from .showroom_util import (fetch_game_tick_packet, set_game_state,
                            spawn_car_for_viewing)
from .start_match_util import create_match_config, start_match_helper
from .story_mode_util import run_challenge, add_match_result


def listen():
    try:
        mp.set_start_method("spawn")
    except RuntimeError:
        pass

    sm = SetupManager()
    online = True

    try:
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
                online = False
            elif params[0] == "fetch-gtp":
                print(f"-|-*|GTP {json.dumps(fetch_game_tick_packet(sm))}|*-|-", flush=True)
            elif params[0] == "set_state":
                state = json.loads(params[1])
                set_game_state(sm, state)
            elif params[0] == "spawn_car_for_viewing":
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
            elif params[0] == "launch_challenge":
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

                completed, results = run_challenge(sm, match_config, challenge, upgrades, RocketLeagueLauncherPreference(preferred_launcher, use_login_tricks, rocket_league_exe_path))

                save_state = add_match_result(save_state, challenge_id, completed, results)

                print(f"-|-*|STORY_RESULT {json.dumps(save_state)}|*-|-", flush=True)
    except Exception:
        print_exc()

    if sm.has_started:
        sm.shut_down(kill_all_pids=True)

    print("Closing...", flush=True)
    exit()
