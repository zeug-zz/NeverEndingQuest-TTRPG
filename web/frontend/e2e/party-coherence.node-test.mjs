// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import { compareHostAndPlayerParty } from "./party-coherence.mjs";

const playerSnapshot = {
  projection: {
    party: {
      members: [{ name: "Aria" }, { name: "Bram" }, { name: "Cato" }, { name: "Dara" }],
      active_character: "Cato",
    },
  },
};
const hostParty = {
  party_members: ["Aria", "Bram", "Cato", "Dara"],
  active_character: "Cato",
};

test("host party response must match player snapshot members and active PC", () => {
  assert.deepEqual(compareHostAndPlayerParty(hostParty, playerSnapshot, 4), {
    matches: true,
    failures: [],
    host_party_names: ["Aria", "Bram", "Cato", "Dara"],
    player_party_names: ["Aria", "Bram", "Cato", "Dara"],
    host_active_character: "Cato",
    player_active_character: "Cato",
  });

  const wrongMember = compareHostAndPlayerParty({
    ...hostParty,
    party_members: ["Aria", "Bram", "Cato", "Other"],
  }, playerSnapshot, 4);
  assert.equal(wrongMember.matches, false);
  assert.ok(wrongMember.failures.includes("party-member-mismatch"));

  const wrongActiveCharacter = compareHostAndPlayerParty({
    ...hostParty,
    active_character: "Dara",
  }, playerSnapshot, 4);
  assert.equal(wrongActiveCharacter.matches, false);
  assert.ok(wrongActiveCharacter.failures.includes("active-character-mismatch"));
});
