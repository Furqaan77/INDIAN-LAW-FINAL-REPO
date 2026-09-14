export interface DiffOp {
  type: "same" | "removed" | "added";
  text: string;
}

/** Share of words that differ across both texts: 0 means identical, 1 means nothing in common. */
export function changedShare(ops: DiffOp[]): number {
  let shared = 0;
  let changed = 0;
  for (const op of ops) {
    const words = op.text.split(" ").length;
    if (op.type === "same") shared += words * 2;
    else changed += words;
  }
  return shared + changed === 0 ? 0 : changed / (shared + changed);
}

/**
 * Word-level longest-common-subsequence diff between two provisions. Returns null when
 * either text is too long for an interactive-speed comparison.
 */
export function diffWords(before: string, after: string, limit = 1800): DiffOp[] | null {
  const a = before.match(/\S+/g) ?? [];
  const b = after.match(/\S+/g) ?? [];
  if (a.length > limit || b.length > limit) return null;

  // Compare on a normalised form so capitalisation and punctuation shifts ("section," vs "Section")
  // aren't reported as substantive changes; the original words are still what gets displayed.
  const normalise = (word: string) => word.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "") || word;
  const keyA = a.map(normalise);
  const keyB = b.map(normalise);

  const width = b.length + 1;
  const lengths = new Uint16Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lengths[i * width + j] =
        keyA[i] === keyB[j]
          ? lengths[(i + 1) * width + j + 1] + 1
          : Math.max(lengths[(i + 1) * width + j], lengths[i * width + j + 1]);
    }
  }

  const ops: DiffOp[] = [];
  const push = (type: DiffOp["type"], word: string) => {
    const last = ops[ops.length - 1];
    if (last?.type === type) last.text += ` ${word}`;
    else ops.push({ type, text: word });
  };

  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (lengths[(i + 1) * width + j] >= lengths[i * width + j + 1]) {
      push("removed", a[i++]);
    } else {
      push("added", b[j++]);
    }
  }
  while (i < a.length) push("removed", a[i++]);
  while (j < b.length) push("added", b[j++]);
  return ops;
}
