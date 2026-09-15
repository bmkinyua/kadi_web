// Shared by write-once.ts / write-different.ts so the persistence
// test isn't tied to guessing field names right in three separate
// places -- deliberately NOT importing SettingsValues from
// packages/renderer (adapters/web has no dependency on that package;
// see PlatformAdapter.ts's docstring on why getSettings/saveSettings
// stay untyped at this layer).
export const SAMPLE_A = {
  turnTimerSecs: 45,
  postPlayDelaySecs: 12,
  counterWindowSecs: 30,
  jokerCount: 4,
  logLevel: 'LOW',
  maxLogPairs: 25,
  timersEnabled: false,
  suitChangeAfterShield: true,
  aceSuitIntegrity: true,
  pickupShieldQkAllowed: false,
  aceFinisherEnabled: false,
  jumpMultiCardEnabled: false,
  cardAnimationsEnabled: false,
  hintsEnabled: true,
  hintThresholdPct: 75,
  musicEnabled: false,
  sfxEnabled: false,
  musicVolume: 0.15,
  sfxVolume: 0.85,
};

export const SAMPLE_B = {
  ...SAMPLE_A,
  turnTimerSecs: 200,
  jokerCount: 2,
  logLevel: 'HIGH',
  musicVolume: 1,
};
