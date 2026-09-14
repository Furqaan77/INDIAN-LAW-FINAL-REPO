import type {
  ActSections,
  CorpusStats,
  DocumentDetail,
  LawMapResponse,
  MappedAct,
  ResearchMode,
  ResearchResult,
  SearchResponse,
  StageEvent,
} from "../types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Non-JSON error body; fall back to the status text below.
  }
  return response.statusText || "The request failed.";
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "Could not reach the IndianLawGPT service.");
  }
  if (!response.ok) throw new ApiError(response.status, await readDetail(response));
  return response.json() as Promise<T>;
}

export const api = {
  stats: (signal?: AbortSignal) => getJson<CorpusStats>("/api/stats", signal),

  document: (docId: string, quotes: string[] = [], signal?: AbortSignal) => {
    const params = new URLSearchParams();
    quotes.forEach((quote) => params.append("quote", quote));
    const query = params.toString();
    return getJson<DocumentDetail>(`/api/documents/${encodeURIComponent(docId)}${query ? `?${query}` : ""}`, signal);
  },

  actSections: (actId: string, signal?: AbortSignal) =>
    getJson<ActSections>(`/api/acts/${encodeURIComponent(actId)}/sections`, signal),

  search: (query: string, type: "statute" | "case_law", signal?: AbortSignal) =>
    getJson<SearchResponse>(`/api/search?${new URLSearchParams({ q: query, type })}`, signal),

  mappedActs: (signal?: AbortSignal) => getJson<{ acts: MappedAct[] }>("/api/law-map/acts", signal),

  lawMap: (act: string, section: string, signal?: AbortSignal) =>
    getJson<LawMapResponse>(`/api/law-map?${new URLSearchParams({ act, section })}`, signal),
};

interface ResearchHandlers {
  onStage: (event: StageEvent) => void;
  onResult: (result: ResearchResult) => void;
  onError: (message: string) => void;
}

function dispatchEvent(raw: string, handlers: ResearchHandlers) {
  let event = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return;
  const payload = JSON.parse(data.join("\n"));
  if (event === "stage") handlers.onStage(payload as StageEvent);
  else if (event === "result") handlers.onResult(payload as ResearchResult);
  else if (event === "error") handlers.onError(payload.message ?? "The research pipeline failed.");
}

/** POSTs a research question and consumes the Server-Sent Event stream it returns. */
export async function streamResearch(
  question: string,
  mode: ResearchMode,
  handlers: ResearchHandlers,
  signal: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, mode }),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") return;
    handlers.onError("Could not reach the IndianLawGPT research service.");
    return;
  }
  if (!response.ok || !response.body) {
    handlers.onError(await readDetail(response));
    return;
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let settled = false;
  const tracked: ResearchHandlers = {
    onStage: handlers.onStage,
    onResult: (result) => {
      settled = true;
      handlers.onResult(result);
    },
    onError: (message) => {
      settled = true;
      handlers.onError(message);
    },
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        dispatchEvent(buffer.slice(0, boundary), tracked);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if ((error as Error).name === "AbortError") return;
    if (!settled) handlers.onError("The connection to the research service was interrupted.");
    return;
  }
  if (!settled) handlers.onError("The research service closed the connection before finishing.");
}
