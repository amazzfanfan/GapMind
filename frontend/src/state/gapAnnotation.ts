export type GapAnnotationProvenance = {
  model_provider: string;
  status: string;
};

export function isRemoteGapFallback(annotation: GapAnnotationProvenance): boolean {
  return annotation.status === "valid" && annotation.model_provider === "remote";
}

export function gapAnnotationProvenanceLabel(annotation: GapAnnotationProvenance): string {
  if (isRemoteGapFallback(annotation)) return "远程降级候选";
  if (annotation.status === "invalid") return "本地标注无效";
  return "本地标注";
}
