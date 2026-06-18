const DEMO_CASE_IDS = new Set<string>(["case_demo"]);
const SANDBOX_PROFILE_IDS = new Set<string>([
  "sandbox.tts.default",
  "sandbox.llm.default",
  "runninghub.heygem.default",
]);

function isSandboxProfileId(id?: string | null): boolean {
  const value = id ?? "";
  return SANDBOX_PROFILE_IDS.has(value) || value.startsWith("sandbox.");
}

export function isRealCase(item: { id: string }): boolean {
  return !DEMO_CASE_IDS.has(item.id);
}

export function isRealVoice(voice: { id: string; provider_profile_id?: string | null }): boolean {
  return voice.id !== "voice_sandbox" && !isSandboxProfileId(voice.provider_profile_id);
}

export function isRealProviderProfile(profile: { provider_id?: string | null }): boolean {
  return (profile.provider_id ?? "") !== "sandbox";
}

function isRealAsset(asset: { id?: string; tags?: readonly string[] | null }): boolean {
  const tags = asset.tags ?? [];
  return !tags.includes("seed") && !(asset.id ?? "").endsWith("_demo");
}

export function isRealAssetCard(card: { asset?: { id?: string; tags?: readonly string[] | null } }): boolean {
  return card.asset ? isRealAsset(card.asset) : true;
}

export function isRealPriceCatalog(catalog: { id?: string; provider_id?: string | null }): boolean {
  return (catalog.provider_id ?? "") !== "sandbox" && catalog.id !== "price_sandbox";
}

export function isRealPriceItem(item: { id?: string; provider_id?: string | null }): boolean {
  return (item.provider_id ?? "") !== "sandbox" && !(item.id ?? "").startsWith("price_sandbox");
}
