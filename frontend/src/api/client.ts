import type {
  CreateModelIn,
  GraphEditIn,
  ModelDetailOut,
  ModelSummaryOut,
  RunDuckDbOut,
  TranspileIn,
  TranspileOut,
  UpdateModelIn,
  UserOut,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

let currentUserId = 1; // default seeded admin

export function setCurrentUserId(id: number): void {
  currentUserId = id;
}

export function getCurrentUserId(): number {
  return currentUserId;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
      "X-User-Id": String(currentUserId),
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new ApiError(res.status, detail?.detail ?? detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  me: () => request<UserOut>("/users/me"),
  listUsers: () => request<UserOut[]>("/users"),

  listModels: () => request<ModelSummaryOut[]>("/models"),
  getModel: (id: number) => request<ModelDetailOut>(`/models/${id}`),
  createModel: (body: CreateModelIn) =>
    request<ModelDetailOut>("/models", { method: "POST", body: JSON.stringify(body) }),
  updateModel: (id: number, body: UpdateModelIn) =>
    request<ModelDetailOut>(`/models/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  updateModelGraph: (id: number, body: GraphEditIn) =>
    request<ModelDetailOut>(`/models/${id}/graph`, { method: "PUT", body: JSON.stringify(body) }),
  deleteModel: (id: number) => request<void>(`/models/${id}`, { method: "DELETE" }),

  transpile: (id: number, body: TranspileIn) =>
    request<TranspileOut>(`/models/${id}/transpile`, { method: "POST", body: JSON.stringify(body) }),

  runDuckDb: (
    id: number,
    args: { mode: "upload" | "demo"; metric: string; groupBy: string[]; file?: File },
  ) => {
    const form = new FormData();
    form.set("mode", args.mode);
    form.set("metric", args.metric);
    form.set("group_by_json", JSON.stringify(args.groupBy));
    if (args.file) form.set("file", args.file);
    return request<RunDuckDbOut>(`/models/${id}/run`, { method: "POST", body: form });
  },

  runTimeSeries: (
    id: number,
    args: {
      mode: "upload" | "demo";
      metric: string;
      timeDataset: string;
      timeField: string;
      grain: string;
      filterGrain?: string;
      filterValue?: string;
      file?: File;
    },
  ) => {
    const form = new FormData();
    form.set("mode", args.mode);
    form.set("metric", args.metric);
    form.set("time_dataset", args.timeDataset);
    form.set("time_field", args.timeField);
    form.set("grain", args.grain);
    if (args.filterGrain) form.set("filter_grain", args.filterGrain);
    if (args.filterValue) form.set("filter_value", args.filterValue);
    if (args.file) form.set("file", args.file);
    return request<RunDuckDbOut>(`/models/${id}/run/timeseries`, { method: "POST", body: form });
  },
};
