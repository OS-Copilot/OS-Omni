"""Windows OpenTwitter v1/v2/v3: only the orders a brief states gate a run.

The ``instruction`` of each task (tasks/v1/windows/opentwitter_*.yaml):

* v1 content_billing: four posts "in the exact order"; the first post of four streams "must each
  be reposted, liked, and saved" (no order between them, no instruction to open them); messages,
  notifications and profile without an order.
* v2 accessibility: "Sign in ..., then publish four consecutive posts ... in the exact order";
  "open the topic streams ... in that specific order"; "Send four direct messages ... in the
  following order".
* v3 launch: posts "in that specific order"; "open the topic streams ... in that specific
  order"; four messages to four recipients "respectively", which pairs, not orders.
* v3 support: posts "in the exact order"; nothing else is ordered.

Repost, like and save are enumerated in every brief, and no brief asks for the Profile page to be
viewed.  Each business action still has to happen exactly once.
"""

from __future__ import annotations

from evaluators.windows import opentwitter_explore as explore
from evaluators.windows.opentwitter_v1_content_billing_596978 import (
    RULESET_SPEC as V1_SPEC,
    OpenTwitterV1ContentBilling596978Evaluator as V1,
)
from evaluators.windows.opentwitter_v2_accessibility_performance_231082 import (
    RULESET_SPEC as V2_SPEC,
    OpenTwitterV2AccessibilityPerformance231082Evaluator as V2,
)
from evaluators.windows.opentwitter_v3_launch_coordination_327435 import (
    RULESET_SPEC as V3L_SPEC,
    OpenTwitterV3LaunchCoordination327435Evaluator as V3L,
)
from evaluators.windows.opentwitter_v3_support_roadmap_976928 import (
    RULESET_SPEC as V3S_SPEC,
    OpenTwitterV3SupportRoadmap976928Evaluator as V3S,
)
from tests.test_windows_opentwitter_first_post import SETS, _App

ORDER = {
    V1: "opentwitter.content_billing.business_order",
    V2: "opentwitter.accessibility.business_order",
    V3L: "opentwitter.launch.business_order",
    V3S: "opentwitter.support.business_order",
}
#: The first posts of the v3 launch streams Release Notes, Reliability and Civic Tech in the shipped
#: seed, as the saved Opus 5.5 run's evaluation recorded them (Product lists p-alex-2001 first).
LAUNCH_POSTS = [
    ("p-1002", "devon", "Reliability", "Post-incident note: the status page now links directly to the mitigation timeline and customer comms draft. That saved three handoffs this morning."),
    ("p-1006", "nora", "Civic Tech", "City transit dashboards should show service changes in plain language first, then link the detailed feed for people who need it."),
    ("p-alex-2009", "alex", "Release Notes", "Release archive cleanup: each launch now has a final decision, owner, known issues, and follow-up date."),
]
REVERSED_CLICKS = ("bookmark", "like", "repost")


class Episode:
    """One episode against the shipped app's behaviour (``_App``), built section by section."""

    def __init__(self, spec: dict, extra_posts=()) -> None:
        self.spec = spec
        self.app = _App()
        for post_id, author, topic, text in extra_posts:
            self.app.users.setdefault(author, {"handle": author, "displayName": author.title(), "bio": ""})
            self.app.posts.append({"id": post_id, "authorHandle": author, "topic": topic, "text": text})
        self.app.login()

    def _query(self, index: int) -> str:
        return self.spec["trend_runtime_queries"][self.spec["trend_queries"][index]]

    def posts(self, order=(0, 1, 2, 3)) -> "Episode":
        for index in order:
            self.app.publish(self.spec["posts"][index])
        return self

    def open_stream(self, index: int) -> "Episode":
        self.app.stream(self._query(index))
        return self

    def streams(self, order=(0, 1, 2, 3), *, clicks=tuple(SETS), opened=True) -> "Episode":
        for index in order:
            query = self._query(index)
            first = self.app.stream(query)[0]
            if not opened:
                self.app.events.pop()  # engaged from elsewhere (e.g. the Home feed), no view
            for action in clicks:
                if not self.app.is_active(first, action):
                    self.app.toggle(first, action)
                    if opened:
                        self.app.stream(query)  # the client refetches the stream after a toggle
        return self

    def messages(self, order=(0, 1, 2, 3)) -> "Episode":
        for index in order:
            row = self.spec["messages"][index]
            self.app.messages.append({"handle": row["handle"], "text": row["text"], "outbound": True})
            self.app.record("message_sent", handle=row["handle"], text=row["text"])
        return self

    def notifications(self) -> "Episode":
        for row in self.app.notifications:
            row["read"] = True
        self.app.record("notifications_marked_read")
        return self

    def profile(self) -> "Episode":
        self.app.rename(self.spec["profile"]["displayName"], self.spec["profile"]["bio"])
        return self

    def failed(self, evaluator) -> set[str]:
        return set(evaluator.evaluate_state(self.app.state()).metadata["failed_checks"])


def _demonstrated(spec: dict, extra_posts=()) -> Episode:
    return Episode(spec, extra_posts).posts().streams().messages().notifications().profile()


# --- every task: the demonstrated order still passes, without a profile view ---------------------

def test_demonstrated_order_passes_without_a_profile_view():
    assert _demonstrated(V1_SPEC).failed(V1) == set()
    assert _demonstrated(V2_SPEC).failed(V2) == set()
    assert _demonstrated(V3L_SPEC, LAUNCH_POSTS).failed(V3L) == set()
    assert _demonstrated(V3S_SPEC).failed(V3S) == set()


# --- v1 content_billing: only the post order is stated -------------------------------------------

def test_v1_sections_streams_and_actions_in_any_order_pass():
    episode = (Episode(V1_SPEC).profile().notifications().messages((3, 2, 1, 0))
               .streams((3, 2, 1, 0), clicks=REVERSED_CLICKS).posts())
    assert episode.failed(V1) == set()


def test_v1_streams_engaged_without_opening_them_pass():
    # Without a view, the stream as it stood at sign-in names the first post.
    assert Episode(V1_SPEC).streams(opened=False).posts().messages().notifications().profile().failed(V1) == set()


def test_v1_posts_out_of_the_stated_order_fail():
    episode = Episode(V1_SPEC).posts((0, 2, 1, 3)).streams().messages().notifications().profile()
    assert episode.failed(V1) == {ORDER[V1]}


def test_v1_duplicate_post_fails():
    episode = Episode(V1_SPEC).posts((0, 1, 1, 2, 3)).streams().messages().notifications().profile()
    assert "opentwitter.content_billing.post_changelog" in episode.failed(V1)


def test_v1_missing_message_fails():
    episode = Episode(V1_SPEC).posts().streams().messages((0, 1, 2)).notifications().profile()
    assert episode.failed(V1) == {"opentwitter.content_billing.message_sofia"}


def test_v1_missing_engagement_fails():
    episode = Episode(V1_SPEC).posts().streams((0, 1, 2)).messages().notifications().profile()
    assert episode.failed(V1) == {"opentwitter.content_billing.trend_changelog_builder"}


# --- v2 accessibility: sign-in then posts, stream opening and messages are stated ----------------

def test_v2_sections_and_actions_in_any_order_pass_when_the_stated_orders_hold():
    episode = (Episode(V2_SPEC).profile().notifications().messages()
               .streams(clicks=REVERSED_CLICKS).posts())
    assert episode.failed(V2) == set()


def test_v2_opening_a_stream_early_or_again_passes():
    episode = Episode(V2_SPEC).posts().open_stream(2).open_stream(0).streams().open_stream(1)
    assert episode.messages().notifications().profile().failed(V2) == set()


def test_v2_streams_opened_out_of_the_stated_order_fail():
    episode = Episode(V2_SPEC).posts().streams((1, 0, 2, 3)).messages().notifications().profile()
    assert episode.failed(V2) == {ORDER[V2]}


def test_v2_messages_out_of_the_stated_order_fail():
    episode = Episode(V2_SPEC).posts().streams().messages((1, 0, 2, 3)).notifications().profile()
    assert episode.failed(V2) == {ORDER[V2]}


def test_v2_posts_out_of_the_stated_order_fail():
    episode = Episode(V2_SPEC).posts((3, 2, 1, 0)).streams().messages().notifications().profile()
    assert episode.failed(V2) == {ORDER[V2]}


def test_v2_streams_have_to_be_opened():
    episode = Episode(V2_SPEC).posts().streams(opened=False).messages().notifications().profile()
    trends = {"opentwitter.accessibility." + name for name in (
        "trend_security_reviews", "trend_frontend_performance", "trend_ai_assistant_rollout", "trend_mobile_release_candidate")}
    assert episode.failed(V2) == trends | {ORDER[V2]}


def test_v2_duplicate_message_fails():
    episode = Episode(V2_SPEC).posts().streams().messages((0, 0, 1, 2, 3)).notifications().profile()
    assert "opentwitter.accessibility.message_hana" in episode.failed(V2)


# --- v3 launch: posts and stream opening are stated; "respectively" is not an order --------------

def test_v3_launch_messages_sections_and_actions_in_any_order_pass():
    episode = (Episode(V3L_SPEC, LAUNCH_POSTS).messages((3, 2, 1, 0)).notifications().profile()
               .posts().streams(clicks=REVERSED_CLICKS))
    assert episode.failed(V3L) == set()


def test_v3_launch_streams_opened_out_of_the_stated_order_fail():
    episode = Episode(V3L_SPEC, LAUNCH_POSTS).posts().streams((0, 2, 1, 3)).messages().notifications().profile()
    assert episode.failed(V3L) == {ORDER[V3L]}


def test_v3_launch_posts_out_of_the_stated_order_fail():
    episode = Episode(V3L_SPEC, LAUNCH_POSTS).posts((1, 0, 2, 3)).streams().messages().notifications().profile()
    assert episode.failed(V3L) == {ORDER[V3L]}


def test_v3_launch_preseeded_like_needs_no_toggle():
    # The shared helper also covers v3 launch now: an action active when the stream was opened
    # stays done (the restored check demanded a fresh activation after the view).
    episode = Episode(V3L_SPEC, LAUNCH_POSTS)
    episode.app.liked.append("p-1002")
    assert episode.posts().streams().messages().notifications().profile().failed(V3L) == set()


# --- v3 support: only the post order is stated ----------------------------------------------------

def test_v3_support_streams_sections_and_actions_in_any_order_pass():
    episode = (Episode(V3S_SPEC).profile().messages((2, 0, 3, 1)).streams((3, 2, 1, 0), clicks=REVERSED_CLICKS)
               .notifications().posts())
    assert episode.failed(V3S) == set()


def test_v3_support_posts_out_of_the_stated_order_fail():
    episode = Episode(V3S_SPEC).posts((0, 1, 3, 2)).streams().messages().notifications().profile()
    assert episode.failed(V3S) == {ORDER[V3S]}


def test_v3_support_duplicate_message_fails():
    episode = Episode(V3S_SPEC).posts().streams().messages((0, 1, 2, 3, 3)).notifications().profile()
    assert "opentwitter.support.message_colerivera31" in episode.failed(V3S)


# --- the helper ----------------------------------------------------------------------------------

def test_stream_views_in_order_finds_a_chain_past_early_and_repeated_views():
    views = [{"seq": seq, "type": "timeline_view", "view": "explore", "query": query}
             for seq, query in enumerate(["B", "A", "A", "C", "B", "C"], start=1)]
    assert [row["seq"] for row in explore.stream_views_in_order(views, ["A", "B", "C"])] == [2, 5, 6]
    assert explore.stream_views_in_order(views, ["C", "A"])[1] is None
