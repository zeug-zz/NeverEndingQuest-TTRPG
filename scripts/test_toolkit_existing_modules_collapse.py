#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Toolkit Existing Modules Collapse - Source Contracts
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.

Provider-free source-contract coverage for the active `/toolkit` Module
Builder sidebar collapse feature (openspec change
`toolkit-existing-modules-collapse`). These tests assert stable markup,
CSS, and JavaScript contracts in `web/templates/module_toolkit.html` and
the isolation boundary against the legacy standalone builder served from
`web/templates/module_builder.html`. No Flask, Socket.IO, browser,
provider, or module fixtures are required.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLKIT_TEMPLATE = REPO_ROOT / "web" / "templates" / "module_toolkit.html"
LEGACY_TEMPLATE = REPO_ROOT / "web" / "templates" / "module_builder.html"


class TestTitleOnlyInitialRendering(unittest.TestCase):
    """Closed-by-default title-first module cards in the active template."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOLKIT_TEMPLATE.read_text(encoding="utf-8")

    def _card_template_block(self) -> str:
        """The innerHTML template used for one module card."""
        start = self.source.index('<summary class="module-summary" aria-expanded="false">')
        return self.source[start : start + 1200]

    def test_module_card_is_native_details_disclosure(self) -> None:
        self.assertIn("document.createElement('details')", self.source)
        self.assertIn("moduleItem.className = 'module-item';", self.source)

    def test_summary_contains_only_indicator_and_title(self) -> None:
        block = self._card_template_block()
        self.assertIn(
            '<span class="module-disclosure-indicator" aria-hidden="true">&gt;</span>',
            block,
        )
        self.assertIn('<span class="module-name">${module.moduleName.replace(/_/g, \' \')}</span>',
                      block)
        self.assertIn("</summary>", block)

    def test_new_cards_have_no_open_attribute(self) -> None:
        block = self._card_template_block()
        self.assertNotIn(" open=", block)
        self.assertNotIn(' open="', block)
        # Initial summary state is closed for assistive technology.
        self.assertIn('aria-expanded="false"', block)

    def test_detail_content_lives_after_summary_in_details_body(self) -> None:
        block = self._card_template_block()
        summary_end = block.index("</summary>")
        level_index = block.index('class="module-level"')
        details_index = block.index('class="module-details"')
        download_index = block.index("downloadAdventure('${module.moduleName}', this)")
        self.assertLess(summary_end, level_index)
        self.assertLess(level_index, details_index)
        self.assertLess(details_index, download_index)

    def test_level_status_and_download_retained_in_detail_body(self) -> None:
        block = self._card_template_block()
        self.assertIn("Levels ${levelRange.min} - ${levelRange.max}", block)
        self.assertIn("Areas:", block)
        self.assertIn("Locations:", block)
        self.assertIn("Plot Points:", block)
        self.assertIn("${module.brief_failure ?", block)
        self.assertIn("${module.media_generator_needed ?", block)
        self.assertIn("Download Adventure", block)


class TestIndividualDisclosureControls(unittest.TestCase):
    """Per-card open/close behavior and state synchronization."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOLKIT_TEMPLATE.read_text(encoding="utf-8")

    def test_summary_sync_helper_uses_native_open_state(self) -> None:
        self.assertIn(
            "summary.setAttribute('aria-expanded', moduleItem.open ? 'true' : 'false');",
            self.source,
        )

    def test_toggle_listener_syncs_session_state_and_banner(self) -> None:
        self.assertIn("moduleItem.addEventListener('toggle', () => {", self.source)
        self.assertIn("syncModuleExpandedState(moduleItem);", self.source)
        self.assertIn("syncModulesBannerState();", self.source)

    def test_toggle_ignores_detached_nodes(self) -> None:
        self.assertIn("if (!moduleItem.isConnected) {", self.source)
        self.assertIn("return;", self.source)

    def test_state_keyed_by_canonical_module_name(self) -> None:
        self.assertIn(
            "const name = moduleItem.getAttribute('data-module-name');", self.source
        )
        self.assertIn("expandedModuleNames.add(name);", self.source)
        self.assertIn("expandedModuleNames.delete(name);", self.source)

    def test_indicator_uses_ascii_gt_and_css_rotates_on_open(self) -> None:
        self.assertIn(".modules-panel .module-item[open] .module-disclosure-indicator {",
                      self.source)
        self.assertIn("transform: rotate(90deg);", self.source)

    def test_summary_is_keyboard_focusable_via_native_semantics(self) -> None:
        # Native summary elements are focusable; the template keeps the
        # indicator inside the summary so it cannot receive focus alone.
        self.assertIn(
            '<span class="module-disclosure-indicator" aria-hidden="true">&gt;</span>',
            self.source,
        )


class TestBulkDisclosureBehavior(unittest.TestCase):
    """Expand/collapse-all banner control contracts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOLKIT_TEMPLATE.read_text(encoding="utf-8")

    def test_banner_control_static_hook_present(self) -> None:
        self.assertIn('id="existing-modules-toggle"', self.source)
        self.assertIn('class="modules-banner-toggle"', self.source)
        self.assertIn('type="button"', self.source)

    def test_banner_click_wired_to_bulk_toggle(self) -> None:
        self.assertIn("function setupExistingModulesToggle() {", self.source)
        self.assertIn("toggle.addEventListener('click', () => {", self.source)
        self.assertIn("toggleAllModules();", self.source)
        self.assertIn("setupExistingModulesToggle();", self.source)

    def test_bulk_intent_derived_from_visible_cards(self) -> None:
        self.assertIn("const allOpen = cards.every(card => card.open);", self.source)
        self.assertIn("card.open = allOpen ? false : true;", self.source)

    def test_bulk_updates_session_state_per_card(self) -> None:
        self.assertIn("cards.forEach(card => {", self.source)
        self.assertIn("syncModuleExpandedState(card);", self.source)
        self.assertIn("syncModulesBannerState();", self.source)

    def test_empty_list_is_safe_noop(self) -> None:
        self.assertIn("const cards = getVisibleModuleCards();", self.source)
        self.assertIn("if (cards.length === 0) {", self.source)
        # Banner derives cards from the rendered container only.
        self.assertIn("querySelectorAll('.module-item')", self.source)

    def test_no_visible_cards_disables_banner(self) -> None:
        self.assertIn("toggle.disabled = true;", self.source)
        self.assertIn("toggle.setAttribute('aria-expanded', 'false');", self.source)
        self.assertIn("toggle.setAttribute('data-modules-banner-state', 'collapsed');",
                      self.source)


class TestRefreshStatePreservation(unittest.TestCase):
    """Page-session expansion state across module-list refreshes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOLKIT_TEMPLATE.read_text(encoding="utf-8")

    def test_session_set_starts_empty(self) -> None:
        self.assertIn("let expandedModuleNames = new Set();", self.source)

    def test_stale_names_pruned_on_refresh(self) -> None:
        self.assertIn(
            "const presentModuleNames = new Set(sortedModules.map(m => m.moduleName));",
            self.source,
        )
        self.assertIn("if (!presentModuleNames.has(name)) {", self.source)
        self.assertIn("expandedModuleNames.delete(name);", self.source)

    def test_expanded_state_reapplied_after_render(self) -> None:
        self.assertIn("if (expandedModuleNames.has(module.moduleName)) {", self.source)
        self.assertIn("moduleItem.open = true;", self.source)
        self.assertIn("syncModuleSummaryExpanded(moduleItem);", self.source)

    def test_new_modules_remain_closed(self) -> None:
        # Reapply is conditional on membership in the session set, so names
        # absent from the set (newly introduced modules) keep native closed
        # details semantics with no `open` attribute.
        reapply_index = self.source.index("if (expandedModuleNames.has(module.moduleName)) {")
        open_index = self.source.index("moduleItem.open = true;", reapply_index)
        self.assertGreater(open_index, reapply_index)

    def test_banner_resynced_after_every_render_path(self) -> None:
        # Both empty-list branches and the populated render path resync the
        # banner from the visible set before returning.
        self.assertEqual(
            self.source.count("No visible cards -> banner becomes a safe"),
            2,
        )
        append_index = self.source.index("modulesListContainer.appendChild(moduleItem);")
        last_banner_sync = self.source.rindex("syncModulesBannerState();")
        self.assertGreater(last_banner_sync, append_index)


class TestAccessibilityAttributes(unittest.TestCase):
    """Assistive-technology exposure for disclosure controls."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOLKIT_TEMPLATE.read_text(encoding="utf-8")

    def test_banner_aria_contract(self) -> None:
        self.assertIn('aria-expanded="false"', self.source)
        self.assertIn('aria-controls="modules-list"', self.source)
        self.assertIn('aria-label="Expand or collapse all modules"', self.source)
        self.assertIn('data-modules-banner-state="collapsed"', self.source)

    def test_banner_state_sync_updates_aria_and_label(self) -> None:
        self.assertIn("toggle.setAttribute('aria-expanded', allOpen ? 'true' : 'false');",
                      self.source)
        self.assertIn(
            "toggle.setAttribute('data-modules-banner-state', allOpen ? 'expanded' : 'collapsed');",
            self.source,
        )
        self.assertIn("label.textContent = allOpen ? 'Collapse all' : 'Expand all';",
                      self.source)

    def test_indicators_hidden_from_assistive_technology(self) -> None:
        self.assertEqual(
            self.source.count('aria-hidden="true">&gt;</span>'), 2
        )

    def test_focus_visibility_for_banner_and_summary(self) -> None:
        self.assertIn(".modules-panel .modules-banner-toggle:focus,", self.source)
        self.assertIn(".modules-panel .modules-banner-toggle:focus-visible {", self.source)
        self.assertIn("outline: 2px solid #FFA500;", self.source)
        self.assertIn(".modules-panel .module-summary:focus {", self.source)
        self.assertIn(".modules-panel .module-summary:focus {\n            outline: none;", self.source)
        self.assertIn(".modules-panel .module-summary:focus-visible {", self.source)
        self.assertIn(
            ".modules-panel .module-summary:focus-visible {\n"
            "            outline: 2px solid #FFA500;\n"
            "            outline-offset: 2px;",
            self.source,
        )
        self.assertNotIn(".modules-panel .module-summary:focus,\n", self.source)

    def test_banner_state_css_indicator(self) -> None:
        self.assertIn(
            '.modules-panel .modules-banner-toggle[data-modules-banner-state="expanded"] .module-disclosure-indicator {',
            self.source,
        )
        self.assertIn("transform: rotate(90deg);", self.source)


class TestExistingPayloadOrderingAndDownloadContract(unittest.TestCase):
    """Task 3.2 - existing module-list payload fields, sidebar status
    markers, level-based ordering, and the Download Adventure request
    contract remain present in the active Toolkit template.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOLKIT_TEMPLATE.read_text(encoding="utf-8")

    def test_level_range_payload_fields_still_rendered(self) -> None:
        self.assertIn(
            "const levelRange = module.levelRange || { min: '?', max: '?' };",
            self.source,
        )
        self.assertIn(
            '<div class="module-level">Levels ${levelRange.min} - ${levelRange.max}</div>',
            self.source,
        )

    def test_area_location_plot_counts_read_from_payload(self) -> None:
        self.assertIn("${module.areaCount || 'N/A'}", self.source)
        self.assertIn("${module.locationCount || 'N/A'}", self.source)
        self.assertIn("${module.plotPointCount || 'N/A'}", self.source)

    def test_sidebar_status_markers_retained(self) -> None:
        self.assertIn("${module.brief_failure ?", self.source)
        self.assertIn('class="module-sidebar-failure"', self.source)
        self.assertIn("${module.media_generator_needed ?", self.source)
        self.assertIn('class="module-sidebar-handoff"', self.source)
        self.assertIn("Needs Module Media Generator", self.source)

    def test_level_based_sorting_logic_remains(self) -> None:
        self.assertIn("const sortedModules = [...validModules].sort((a, b) => {", self.source)
        self.assertIn("const aMin = parseLevelValue(aRange.min);", self.source)
        self.assertIn("if (aMin !== bMin) return aMin - bMin;", self.source)
        self.assertIn("const aMax = parseLevelValue(aRange.max);", self.source)
        self.assertIn("if (aMax !== bMax) return aMax - bMax;", self.source)
        self.assertIn("(a.moduleName || '').localeCompare(b.moduleName || '');", self.source)

    def test_ordered_list_feeds_the_render_loop(self) -> None:
        # Cards are rendered from the sorted list, so the sidebar preserves
        # the existing level-based order instead of a new ordering scheme.
        sort_start = self.source.index("const sortedModules = [...validModules].sort((a, b) => {")
        render_start = self.source.index("sortedModules.forEach(module => {", sort_start)
        self.assertGreater(render_start, sort_start)

    def test_download_action_still_rendered(self) -> None:
        self.assertIn("Download Adventure", self.source)
        self.assertIn("onclick=\"downloadAdventure('${module.moduleName}', this)\"", self.source)

    def test_download_uses_module_specific_adventure_endpoint(self) -> None:
        self.assertIn("async function downloadAdventure(moduleName, btn) {", self.source)
        self.assertIn(
            "const response = await fetch(`/api/toolkit/modules/${moduleName}/adventure.md`);",
            self.source,
        )
        self.assertIn("a.download = `${moduleName}_adventure.md`;", self.source)


class TestLegacyModuleBuilderIsolation(unittest.TestCase):
    """The standalone legacy builder must not gain collapse behavior."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.legacy = LEGACY_TEMPLATE.read_text(encoding="utf-8")

    def test_legacy_template_has_no_banner_toggle(self) -> None:
        self.assertNotIn("existing-modules-toggle", self.legacy)
        self.assertNotIn("modules-banner-toggle", self.legacy)
        self.assertNotIn("data-modules-banner-state", self.legacy)

    def test_legacy_template_has_no_collapse_js(self) -> None:
        for identifier in (
            "expandedModuleNames",
            "toggleAllModules",
            "getVisibleModuleCards",
            "syncModulesBannerState",
            "syncModuleExpandedState",
            "syncModuleSummaryExpanded",
            "data-module-name",
        ):
            self.assertNotIn(identifier, self.legacy)

    def test_legacy_cards_remain_always_visible_divs(self) -> None:
        self.assertIn("document.createElement('div');", self.legacy)
        self.assertIn("moduleItem.className = 'module-item';", self.legacy)
        card_start = self.legacy.index("moduleItem.innerHTML = `")
        card_block = self.legacy[card_start : card_start + 800]
        self.assertIn('<div class="module-name">', card_block)
        self.assertNotIn("<summary", card_block)
        self.assertNotIn("aria-expanded", card_block)

    def test_legacy_retains_existing_detail_content(self) -> None:
        self.assertIn('<div class="module-level">', self.legacy)
        self.assertIn('<div class="module-details">', self.legacy)
        self.assertIn('<span>Areas:</span>', self.legacy)
        self.assertIn('<span>Locations:</span>', self.legacy)
        self.assertIn('<span>Plot Points:</span>', self.legacy)
        self.assertIn("${module.brief_failure ?", self.legacy)
        self.assertIn("${module.media_generator_needed ?", self.legacy)


if __name__ == "__main__":
    unittest.main()
