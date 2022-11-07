from time import sleep
from traceback import print_exc
from typing import List, Optional
import multiprocessing as mp

from rlbot.matchconfig.match_config import (MatchConfig, MutatorConfig,
                                            PlayerConfig, ScriptConfig)
from rlbot.matchconfig.psyonix_config import set_random_psyonix_bot_preset
from rlbot.parsing.agent_config_parser import load_bot_appearance
from rlbot.parsing.bot_config_bundle import get_bot_config_bundle
from rlbot.parsing.incrementing_integer import IncrementingInteger
from rlbot.setup_manager import RocketLeagueLauncherPreference, SetupManager
from rlbot.utils import logging_utils

from .custom_map_util import identify_map_directory, prepare_custom_map

logger = logging_utils.get_logger("match_handler")


def create_player_config(bot: dict, human_index_tracker: IncrementingInteger):
    player_config = PlayerConfig()
    player_config.bot = bot['runnable_type'] in ('rlbot', 'psyonix')
    player_config.rlbot_controlled = bot['runnable_type'] in ('rlbot', 'party_member_bot')
    player_config.bot_skill = bot['skill']
    player_config.human_index = 0 if player_config.bot else human_index_tracker.increment()
    player_config.name = bot['name']
    player_config.team = int(bot['team'])

    if 'path' in bot and bot['path']:
        bot_path = bot['path']
        player_config.config_path = bot_path
        config = get_bot_config_bundle(bot_path)
        loadout = load_bot_appearance(config.get_looks_config(), player_config.team)
        player_config.loadout_config = loadout
    elif player_config.bot and not player_config.rlbot_controlled:
        set_random_psyonix_bot_preset(player_config)
    
    return player_config


def create_script_config(script):
    return ScriptConfig(script['path'])


def setup_match(
    setup_manager: SetupManager, match_config: MatchConfig, launcher_pref: RocketLeagueLauncherPreference, out: Optional[mp.Queue] = None
):
    """Starts the match and bots. Also detects and handles custom maps"""

    def do_setup():
        setup_manager.early_start_seconds = 5
        setup_manager.connect_to_game(launcher_preference=launcher_pref)

        # Loading the setup manager's game interface just as a quick fix because story mode uses it. Ideally story mode
        # should now make its own game interface to use.
        setup_manager.game_interface.load_interface(wants_ball_predictions=False, wants_quick_chat=False, wants_game_messages=False)
        setup_manager.load_match_config(match_config)
        setup_manager.launch_early_start_bot_processes()
        setup_manager.start_match()
        setup_manager.launch_bot_processes()

        if out is not None:
            out.put("done")

        logger.info("Waiting to recieve metadata from all bots...")

        times_waited = 0
        # wait for all metadata, or for 10 seconds
        while not setup_manager.has_received_metadata_from_all_bots() and times_waited < 40:
            if times_waited != 0:
                expected_metadata = sum(1 for player in setup_manager.match_config.player_configs if player.rlbot_controlled)
                needed_metadata = expected_metadata - setup_manager.num_metadata_received
                logger.info(f"Waiting for metadata from {needed_metadata} bot{'s' if needed_metadata > 1 else ''}...")
                sleep(0.25)
            times_waited += 1
            setup_manager.try_recieve_agent_metadata()

        if not setup_manager.has_received_metadata_from_all_bots():
            expected_metadata = sum(1 for player in setup_manager.match_config.player_configs if player.rlbot_controlled)
            logger.warning(f"Did not receive metadata from all bots. Expected {expected_metadata} but only got {setup_manager.num_metadata_received}")

    map_file = match_config.game_map
    if map_file.endswith('.upk') or map_file.endswith('.udk'):
        rl_directory = identify_map_directory(launcher_pref)

        if not rl_directory:
            raise Exception("Couldn't find path to Rocket League maps folder")

        with prepare_custom_map(map_file, rl_directory) as (map_file, metadata):
            match_config.game_map = map_file
            if "config_path" in metadata:
                config_path = metadata["config_path"]
                match_config.script_configs.append(
                    create_script_config({'path': config_path}))
                logger.info(f"Will load custom script for map {config_path}")
            do_setup()
    else:
        do_setup()


def create_match_config(bot_list: List[dict], match_settings: dict) -> MatchConfig:
    match_config = MatchConfig()
    match_config.game_mode = match_settings['game_mode']
    match_config.game_map = match_settings['map']
    match_config.skip_replays = match_settings['skip_replays']
    match_config.instant_start = match_settings['instant_start']
    match_config.enable_lockstep = match_settings['enable_lockstep']
    match_config.enable_rendering = match_settings['enable_rendering']
    match_config.enable_state_setting = match_settings['enable_state_setting']
    match_config.auto_save_replay = match_settings['auto_save_replay']
    match_config.existing_match_behavior = match_settings['match_behavior']
    match_config.mutators = MutatorConfig()

    mutators = match_settings['mutators']
    match_config.mutators.match_length = mutators['match_length']
    match_config.mutators.max_score = mutators['max_score']
    match_config.mutators.overtime = mutators['overtime']
    match_config.mutators.series_length = mutators['series_length']
    match_config.mutators.game_speed = mutators['game_speed']
    match_config.mutators.ball_max_speed = mutators['ball_max_speed']
    match_config.mutators.ball_type = mutators['ball_type']
    match_config.mutators.ball_weight = mutators['ball_weight']
    match_config.mutators.ball_size = mutators['ball_size']
    match_config.mutators.ball_bounciness = mutators['ball_bounciness']
    match_config.mutators.boost_amount = mutators['boost_amount']
    match_config.mutators.rumble = mutators['rumble']
    match_config.mutators.boost_strength = mutators['boost_strength']
    match_config.mutators.gravity = mutators['gravity']
    match_config.mutators.demolish = mutators['demolish']
    match_config.mutators.respawn_time = mutators['respawn_time']

    human_index_tracker = IncrementingInteger(0)
    match_config.player_configs = [create_player_config(bot, human_index_tracker) for bot in bot_list]
    match_config.script_configs = [create_script_config(script) for script in match_settings['scripts']]

    return match_config


def start_match_wrapper(sm: SetupManager, match_config: MatchConfig, launcher_prefs: RocketLeagueLauncherPreference, out: Optional[mp.Queue] = None):
    logger.info(f"Launcher preferences: {launcher_prefs}")

    # these fancy prints will not get printed to the console
    # the Rust port of the RLBotGUI will capture it and fire a tauri event

    try:
        setup_match(sm, match_config, launcher_prefs, out)
        print("-|-*|MATCH STARTED|*-|-", flush=True)
    except Exception:
        print_exc()
        print("-|-*|MATCH START FAILED|*-|-", flush=True)


def start_match_helper(sm: SetupManager, bot_list: List[dict], match_settings: dict, launcher_prefs: RocketLeagueLauncherPreference, out: Optional[mp.Queue] = None):
    start_match_wrapper(sm, create_match_config(bot_list, match_settings), launcher_prefs, out)
