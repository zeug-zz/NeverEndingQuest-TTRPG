// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export function compareHostAndPlayerParty(hostParty, playerSnapshot, expectedPartySize) {
  const hostNames = Array.isArray(hostParty?.party_members) ? hostParty.party_members : [];
  const playerNames = Array.isArray(playerSnapshot?.projection?.party?.members)
    ? playerSnapshot.projection.party.members.map((member) => member.name)
    : [];
  const hostActiveCharacter = hostParty?.active_character ?? null;
  const playerActiveCharacter = playerSnapshot?.projection?.party?.active_character ?? null;
  const sameMembers = hostNames.length === playerNames.length &&
    hostNames.every((name, index) => name === playerNames[index]);
  const failures = [];

  if (hostNames.length !== expectedPartySize) failures.push("host-party-size-mismatch");
  if (playerNames.length !== expectedPartySize) failures.push("player-party-size-mismatch");
  if (!sameMembers) failures.push("party-member-mismatch");
  if (typeof hostActiveCharacter !== "string" || hostActiveCharacter.length === 0) {
    failures.push("host-active-character-missing");
  }
  if (hostActiveCharacter !== playerActiveCharacter) failures.push("active-character-mismatch");

  return {
    matches: failures.length === 0,
    failures,
    host_party_names: hostNames,
    player_party_names: playerNames,
    host_active_character: hostActiveCharacter,
    player_active_character: playerActiveCharacter,
  };
}
