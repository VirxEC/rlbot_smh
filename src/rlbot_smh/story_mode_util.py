import platform
import random
import time
from datetime import datetime
from multiprocessing import Queue as MPQueue
from traceback import print_exc
from typing import Tuple

from rlbot.matchconfig.match_config import MatchConfig, MutatorConfig
from rlbot.parsing.match_settings_config_parser import (game_mode_types,
                                                        match_length_types)
from rlbot.setup_manager import RocketLeagueLauncherPreference, SetupManager
from rlbot.utils.game_state_util import CarState, GameState
from rlbot.utils.structures.game_data_struct import GameTickPacket

from .start_match_util import start_match_wrapper

WITNESS_ID = random.randint(0, 1e5)
RENDERING_GROUP = "STORY"

DEBUG_MODE_SHORT_GAMES = False

def setup_failure_freeplay(setup_manager: SetupManager, message: str, color_key="red"):
    setup_manager.shut_down()
    match_config = MatchConfig()
    match_config.game_mode = game_mode_types[0]
    match_config.game_map = "BeckwithPark"
    match_config.enable_rendering = True

    mutators = MutatorConfig()
    mutators.match_length = match_length_types[3]
    match_config.mutators = mutators

    match_config.player_configs = []

    setup_manager.load_match_config(match_config)
    setup_manager.start_match()

    # wait till num players is 0
    wait_till_cars_spawned(setup_manager, 0)

    color = getattr(setup_manager.game_interface.renderer, color_key)()
    setup_manager.game_interface.renderer.begin_rendering(RENDERING_GROUP)
    # setup_manager.game_interface.renderer.draw_rect_2d(20, 20, 800, 800, True, setup_manager.game_interface.renderer.black())
    setup_manager.game_interface.renderer.draw_string_2d(20, 200, 4, 4, message, color)
    setup_manager.game_interface.renderer.end_rendering()


def packet_to_game_results(game_tick_packet: GameTickPacket):
    """Take the final game_tick_packet and
    returns the info related to the final game results
    """
    players = game_tick_packet.game_cars
    human_player = next(p for p in players if not p.is_bot)

    player_stats = [
        {
            "name": p.name,
            "team": p.team,
            # these are always 0, so we don't add them
            # "spawn_id": p.spawn_id,
            # "score": p.score_info.score,
            # "goals": p.score_info.goals,
            # "own_goals": p.score_info.own_goals,
            # "assists": p.score_info.assists,
            # "saves": p.score_info.saves,
            # "shots": p.score_info.shots,
            # "demolitions": p.score_info.demolitions
        }
        for p in players
        if p.name
    ]


    if platform.system() == "Windows":
        # team_index = gamePacket.teams[i].team_index
        # new_score = gamePacket.teams[i].score
        scores_sorted = [
            {"team_index": t.team_index, "score": t.score} for t in game_tick_packet.teams
        ]
    else:
        # gotta love them bugs! juicy!!!
        # team_index = gamePacket.teams[i].score - 1
        # new_score = gamePacket.teams[i].team_index
        scores_sorted = [
            {"team_index": t.score - 1, "score": t.team_index} for t in game_tick_packet.teams
        ]

    scores_sorted.sort(key=lambda x: x["score"], reverse=True)
    human_won = scores_sorted[0]["team_index"] == human_player.team

    return {
        "human_team": human_player.team,
        "score": scores_sorted,  # [{team_index, score}]
        "stats": player_stats,
        "human_won": human_won,
        "timestamp": datetime.now().isoformat(),
    }


def has_user_perma_failed(challenge, manual_stats):
    """
    Check if the user has perma-failed the challenge
    meaning more time in the game doesn't change the result
    """
    if "completionConditions" not in challenge:
        return False
    failed = False
    completionConditions = challenge["completionConditions"]

    if "selfDemoCount" in completionConditions:
        survived = (
            manual_stats["recievedDemos"] <= completionConditions["selfDemoCount"]
        )
        failed = failed or not survived
    return failed

def end_by_mercy(challenge, manual_stats, results):
    """Returns true if the human team is ahead by a lot
    and the other challenges have finished"""
    challenge_completed = calculate_completion(challenge, manual_stats, results)

    mercy_difference = 5
    # ignore the team, just look at the differential
    score_differential = results["score"][0]["score"] - results["score"][1]["score"]

    return score_differential >= mercy_difference and challenge_completed


def calculate_completion(challenge, manual_stats, results):
    """
    parse challenge to file completionConditions and evaluate
    each.
    All conditions are "and"
    """
    completed = results["human_won"]
    if "completionConditions" not in challenge:
        return completed

    if has_user_perma_failed(challenge, manual_stats):
        return False

    completionConditions = challenge["completionConditions"]

    if not completionConditions.get("win", True):
        # the "win" requirement is explicitly off
        completed = True

    if "scoreDifference" in completionConditions:
        # ignore the team, jsut look at the differential
        condition = completionConditions["scoreDifference"]
        difference = results["score"][0]["score"] - results["score"][1]["score"]
        completed = completed and (difference >= condition)

    if "demoAchievedCount" in completionConditions:
        achieved = (
            manual_stats["opponentRecievedDemos"]
            >= completionConditions["demoAchievedCount"]
        )
        completed = completed and achieved

    if "goalsScored" in completionConditions:
        achieved = manual_stats["humanGoalsScored"] >= completionConditions["goalsScored"]
        completed = completed and achieved

    return completed


class ManualStatsTracker:
    def __init__(self, challenge):
        self.stats = {
            "recievedDemos": 0,  # how many times the human got demo'd
            "opponentRecievedDemos": 0,  # how many times the opponents were demo'd
            "humanGoalsScored": 0,
        }

        self._challenge = challenge
        self._player_count = challenge["humanTeamSize"] + len(challenge["opponentBots"])

        # helper to find discrete demo events
        self._in_demo_state = [False] * self._player_count
        # helper to find who scored!
        self._last_touch_by_team = [None, None]
        self._last_score_by_team = [0, 0]

    def updateStats(self, gamePacket: GameTickPacket):
        """
        Update and track stats based on the game packet
        """
        # keep track of demos
        for i in range(len(self._in_demo_state)):
            cur_player = gamePacket.game_cars[i]
            if self._in_demo_state[i]:  # we will toggle this if we have respawned
                self._in_demo_state[i] = cur_player.is_demolished
            elif cur_player.is_demolished:
                print("SOMEONE GOT DEMO'd")
                self._in_demo_state[i] = True
                if not gamePacket.game_cars[i].is_bot:
                    self.stats["recievedDemos"] += 1
                elif i >= self._challenge["humanTeamSize"]:
                    # its an opponent bot
                    self.stats["opponentRecievedDemos"] += 1

        touch = gamePacket.game_ball.latest_touch
        team = touch.team
        self._last_touch_by_team[team] = touch

        for i in range(2):  # iterate of [{team_index, score}]
            if platform.system() == "Windows":
                team_index = gamePacket.teams[i].team_index
                new_score = gamePacket.teams[i].score
            else:
                # gotta love them bugs! juicy!!!
                team_index = gamePacket.teams[i].score - 1
                new_score = gamePacket.teams[i].team_index
            if new_score != self._last_score_by_team[team_index]:
                self._last_score_by_team[team_index] = new_score

                if self._last_touch_by_team[team_index] is not None:
                    last_touch_player = self._last_touch_by_team[team_index].player_index
                    last_touch_player_name = self._last_touch_by_team[team_index].player_name
                    if not gamePacket.game_cars[last_touch_player].is_bot and last_touch_player_name != "":
                        self.stats["humanGoalsScored"] += 1
                        print("humanGoalsScored")


def wait_till_cars_spawned(
    setup_manager: SetupManager, expected_player_count: int
) -> GameTickPacket:
    packet = GameTickPacket()
    setup_manager.game_interface.fresh_live_data_packet(packet, 1000, WITNESS_ID)
    waiting_start = time.monotonic()
    while packet.num_cars != expected_player_count and time.monotonic() - waiting_start < 5:
        print("Game started but no cars are in the packets")
        time.sleep(0.5)
        setup_manager.game_interface.fresh_live_data_packet(packet, 1000, WITNESS_ID)

    return packet


def manage_game_state(
    challenge: dict, upgrades: dict, setup_manager: SetupManager
) -> Tuple[bool, dict]:
    """
    Continuously track the game and adjust state to respect challenge rules and
    upgrades.
    At the end of the game, calculate results and the challenge completion
    and return that
    """
    early_failure = False, None

    expected_player_count = challenge["humanTeamSize"] + len(challenge["opponentBots"])
    # Wait for everything to be initialized
    packet = wait_till_cars_spawned(setup_manager, expected_player_count)

    if packet.num_cars == 0:
        print("The game was initialized with no cars")
        return early_failure

    tick_rate = 120
    results = None
    max_boost = 0
    if "boost-100" in upgrades:
        max_boost = 100
    elif "boost-33" in upgrades:
        max_boost = 33

    half_field = challenge.get("limitations", []).count("half-field") > 0

    stats_tracker = ManualStatsTracker(challenge)
    last_boost_bump_time = time.monotonic()
    while True:
        try:
            packet = GameTickPacket()
            setup_manager.game_interface.fresh_live_data_packet(
                packet, 1000, WITNESS_ID
            )

            if packet.num_cars == 0:
                # User seems to have ended the match
                print("User ended the match")
                return early_failure

            stats_tracker.updateStats(packet)
            results = packet_to_game_results(packet)

            if has_user_perma_failed(challenge, stats_tracker.stats):
                time.sleep(1)
                setup_failure_freeplay(setup_manager, "You failed the challenge!")
                return early_failure

            if end_by_mercy(challenge, stats_tracker.stats, results):
                time.sleep(3)
                setup_failure_freeplay(setup_manager, "Challenge completed by mercy rule!", "green")
                return True, results

            human_info = packet.game_cars[0]
            game_state = GameState()
            human_desired_state = CarState()
            game_state.cars = {0: human_desired_state}

            changed = False
            # adjust boost
            if human_info.boost > max_boost and not half_field:
                # Adjust boost, unless in heatseeker mode
                human_desired_state.boost_amount = max_boost
                changed = True

            if "boost-recharge" in upgrades:
                # increase boost at 10% per second
                now = time.monotonic()
                if human_info.boost < max_boost and (now - last_boost_bump_time > 0.1):
                    changed = True
                    last_boost_bump_time = now
                    human_desired_state.boost_amount = min(human_info.boost + 1, max_boost)

            if changed:
                setup_manager.game_interface.set_game_state(game_state)

            if packet.game_info.is_match_ended:
                break

        except KeyError:
            print_exc()
            # it means that the game was interrupted by the user
            print("Looks like the game is in a bad state")
            setup_failure_freeplay(setup_manager, "The game was interrupted.")
            return early_failure

    return calculate_completion(challenge, stats_tracker.stats, results), results


def run_challenge(
    setup_manager: SetupManager, match_config: MatchConfig, challenge: dict, upgrades: dict, launcher_pref: RocketLeagueLauncherPreference, out: MPQueue
) -> Tuple[bool, dict]:
    """Launch the game and keep track of the state"""
    start_match_wrapper(setup_manager, match_config, launcher_pref, out)

    setup_manager.game_interface.renderer.clear_screen(RENDERING_GROUP)
    game_results = None
    try:
        game_results = manage_game_state(challenge, upgrades, setup_manager)
    except:
        # no matter what happens we gotta continue
        print_exc()
        print("Something failed with the game. Will proceed with shutdown")
        # need to make failure apparent to user
        setup_failure_freeplay(setup_manager, "The game failed to continue")
        return False, None

    return game_results


def add_match_result(save_state, challenge_id: str, challenge_completed: bool, game_results):
    """game_results should be the output of packet_to_game_results.
    You have to call it anyways to figure out if the player
    completed the challenge so that's why we don't call it again here.
    """
    if challenge_id not in save_state["challenges_attempts"]:
        # no defaultdict because we serialize the data
        save_state["challenges_attempts"][challenge_id] = []

    save_state["challenges_attempts"][challenge_id].append(
        {"game_results": game_results, "challenge_completed": challenge_completed}
    )

    if challenge_completed:
        index = len(save_state["challenges_attempts"][challenge_id]) - 1
        save_state["challenges_completed"][challenge_id] = index
        save_state["upgrades"]["currency"] += 2

    return save_state
