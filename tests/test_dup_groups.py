"""Unit tests for the duplicate-group index (same file + exact EN + matching
source tag/times) and the group edit propagation."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "vendor")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tr_edit_core import (
    GroupMember,
    Item,
    Store,
    apply_group_edit,
    authored_signature,
    canonical_member,
    duplicate_groups,
    group_for,
)


class FakeStore(Store):
    """Store with scripted EN text + source tag/times (no game dir needed)."""

    def __init__(self, rows, tags, times):
        super().__init__(game_dir=None)
        self.game = "fake"
        self.tables = {f: {k: vn for k, (_en, vn) in r.items()}
                       for f, r in rows.items()}
        self._en_map = {f: {k: en for k, (en, _vn) in r.items()}
                        for f, r in rows.items()}
        self._tag_map = tags
        self._times_map = times

    def id_text_map(self, file):
        return self._en_map.get(file, {})

    def en_tag_spans(self, file):
        return self._tag_map.get(file, {})

    def en_times_offsets(self, file, ids):
        for rid in ids:
            if rid in self._times_map.get(file, {}):
                return self._times_map[file][rid]
        return []


def make_store(rows, tags=None, times=None):
    """Build a fake Store for ``{file: {key: (en, vn)}}`` rows.

    ``tags`` follows the ``en_tag_spans`` shape ``{file: {(rid, subid):
    {key: [(s, e), ...]}}}``; ``times`` the ``en_times_offsets`` shape
    ``{file: {rid: [offset, ...]}}``.
    """
    return FakeStore(rows, tags or {}, times or {})


class DupGroupsTest(unittest.TestCase):
    def test_same_en_same_file_groups(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", ""),
            "ccc": ("Bye", "")}})
        groups = duplicate_groups(s)
        self.assertEqual(len(groups), 1)
        members = next(iter(groups.values()))
        self.assertEqual(sorted(m.key for m in members), ["aaa", "bbb"])

    def test_different_en_not_grouped(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("World", "")}})
        self.assertEqual(duplicate_groups(s), {})

    def test_different_file_not_grouped(self):
        s = make_store({
            "text_a.msg": {"aaa": ("Hello", "")},
            "text_b.msg": {"bbb": ("Hello", "")}})
        self.assertEqual(duplicate_groups(s), {})

    def test_empty_en_skipped(self):
        s = make_store({
            "text_a.msg": {"aaa": ("", ""), "bbb": ("", "")}})
        self.assertEqual(duplicate_groups(s), {})

    def test_tag_sig_differs_not_grouped(self):
        tags = {"text_a.msg": {("aaa", ""): {"colors_": [(0, 5)]}}}
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}}, tags=tags)
        self.assertEqual(duplicate_groups(s), {})

    def test_times_sig_differs_not_grouped(self):
        times = {"text_a.msg": {"aaa": [1, 3]}}
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}}, times=times)
        self.assertEqual(duplicate_groups(s), {})

    def test_canonical_member_first_nonempty(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "Xin chào"),
            "ccc": ("Hello", "")}})
        group = next(iter(duplicate_groups(s).values()))
        self.assertEqual(canonical_member(group).key, "bbb")

    def test_group_for_item(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", "Xin chào"), "bbb": ("Hello", "Xin chào")}})
        item = Item(s, "text_a.msg", "aaa", "Xin chào")
        group = group_for(s, item)
        self.assertIsNotNone(group)
        self.assertEqual(len(group), 2)

    def test_apply_group_edit_propagates(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", ""), "ccc": ("Hello", "")}})
        group = next(iter(duplicate_groups(s).values()))
        warnings = apply_group_edit(s, group, "{c:Hello}")
        self.assertEqual(warnings, [])
        for m in group:
            self.assertEqual(s.tables["text_a.msg"][m.key], "Hello")
            dec = s.decisions["text_a"].get(m.ids[0], {}).get("colors_")
            self.assertEqual(dec.get("0"), ["Hello"])
            ov = s.overrides["text_a"].get(m.ids[0], {}).get("colors_")
            self.assertEqual(ov.get("0"), [0, 5])

    def test_duplicate_groups_cached(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}})
        self.assertIs(duplicate_groups(s), duplicate_groups(s))

    def _gm(self, s, key):
        file, vn = next((f, s.tables[f][key])
                        for f in s.tables if key in s.tables[f])
        return GroupMember(s, file, key, vn, 0, 0)

    def test_authored_signature_equals(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", "Xin chào"), "bbb": ("Hello", "Xin chào")}})
        self.assertEqual(authored_signature(s, self._gm(s, "aaa")),
                         authored_signature(s, self._gm(s, "bbb")))

    def test_authored_signature_vn_differs(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", "Xin chào"), "bbb": ("Hello", "Chào")}})
        self.assertNotEqual(authored_signature(s, self._gm(s, "aaa")),
                            authored_signature(s, self._gm(s, "bbb")))

    def test_authored_signature_decisions_diff(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", "Xin chào"), "bbb": ("Hello", "Xin chào")}})
        s.decisions = {"text_a": {"aaa": {"colors_": {"0": ["Hello"]}}}}
        self.assertNotEqual(authored_signature(s, self._gm(s, "aaa")),
                            authored_signature(s, self._gm(s, "bbb")))

    def test_authored_signature_overrides_diff(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", "Xin chào"), "bbb": ("Hello", "Xin chào")}})
        s.overrides = {"text_a": {"bbb": {"times_": {"0": [0, 3]}}}}
        self.assertNotEqual(authored_signature(s, self._gm(s, "aaa")),
                            authored_signature(s, self._gm(s, "bbb")))

    def test_authored_signature_after_group_edit_equals(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "Xin chào")}})
        group = next(iter(duplicate_groups(s).values()))
        apply_group_edit(s, group, "{c:Hello}")
        self.assertEqual(authored_signature(s, self._gm(s, "aaa")),
                         authored_signature(s, self._gm(s, "bbb")))

    def test_authored_signature_reads_live_vn(self):
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}})
        group = next(iter(duplicate_groups(s).values()))
        stale = group[0]  # cached member with vn="" before the edit
        apply_group_edit(s, group, "{c:Hello}")
        self.assertEqual(authored_signature(s, stale)[0], "Hello")

    def test_group_edit_refreshes_cached_vn(self):
        # Regression: the group index was built while every member was
        # untranslated, so canonical_member would pick a ""-vn row. After a
        # group save the cached vn must be refreshed, otherwise the duplicate
        # check marks every member as out-of-sync (stale canonical "").
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}})
        group = next(iter(duplicate_groups(s).values()))
        apply_group_edit(s, group, "Được thôi. Cứ để lo.")
        self.assertEqual([m.vn for m in group],
                         ["Được thôi. Cứ để lo."] * len(group))
        canon = canonical_member(group)
        self.assertEqual(canon.vn, "Được thôi. Cứ để lo.")
        sig = authored_signature(s, canon)
        for m in group:
            self.assertEqual(authored_signature(s, m), sig)

    def test_group_edit_unifies_times(self):
        # A member carrying a manual times_ override defines the group's shared
        # voice sync; saving stamps it onto every member so all stay ✓.
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}})
        s.overrides = {"text_a": {"aaa": {"times_": {"0": [10, 10]}}}}
        s.tuned = {"files": {"text_a": {"t0": {"id_": "aaa", "times_": [
            {"Element": {"time_": 1.0, "wait_": False,
                         "start_": 5, "end_": 5}}]}}}}
        group = next(iter(duplicate_groups(s).values()))
        apply_group_edit(s, group, "Xin chào")
        self.assertEqual(s.overrides["text_a"]["bbb"]["times_"], {"0": [10, 10]})
        self.assertEqual(authored_signature(s, group[0]),
                         authored_signature(s, group[1]))

    def test_group_edit_keeps_times_untouched_when_none(self):
        # No member has a times_ override -> saving must not materialize the
        # game default into tag_overrides.json.
        s = make_store({"text_a.msg": {
            "aaa": ("Hello", ""), "bbb": ("Hello", "")}})
        s.tuned = {"files": {"text_a": {"t0": {"id_": "aaa", "times_": [
            {"Element": {"time_": 1.0, "wait_": False,
                         "start_": 5, "end_": 5}}]}}}}
        group = next(iter(duplicate_groups(s).values()))
        apply_group_edit(s, group, "Xin chào")
        for m in group:
            rec = s.overrides.get("text_a", {}).get(m.ids[0], {})
            self.assertNotIn("times_", rec)


if __name__ == "__main__":
    unittest.main()