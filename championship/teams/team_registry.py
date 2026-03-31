from __future__ import annotations

from championship.models import Team


class TeamRegistry:
    def __init__(self) -> None:
        self.max_teams = 4
        self.max_team_size = 3

    def validate_team(self, team: Team) -> None:
        if len(team.bot_ids) > self.max_team_size:
            raise ValueError("Team cannot contain more than 3 bots.")
