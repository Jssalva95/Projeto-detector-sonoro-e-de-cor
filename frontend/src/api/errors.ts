export type ApiErrorKind = "http" | "network" | "cancelled" | "invalid_response" | "invalid_request";
export interface ValidationIssue {
  location: ReadonlyArray<string | number>;
  type: string;
}

const messages: Record<number, string> = {
  401: "É necessário autenticar-se para continuar.",
  403: "Você não tem permissão para esta operação.",
  404: "O registro solicitado não foi encontrado.",
  409: "A operação conflita com um registro ou vínculo existente.",
  422: "Verifique os dados informados.",
  429: "Aguarde antes de solicitar esta operação novamente.",
  503: "O serviço está temporariamente indisponível.",
};

export class ApiError extends Error {
  constructor(
    public readonly kind: ApiErrorKind,
    message: string,
    public readonly status?: number,
    public readonly issues: readonly ValidationIssue[] = [],
    public readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function httpError(status: number, payload: unknown, retryAfter: string | null): ApiError {
  const issues: ValidationIssue[] = [];
  if (status === 422 && isRecord(payload) && Array.isArray(payload.detail)) {
    for (const item of payload.detail) {
      if (isRecord(item) && Array.isArray(item.loc) && typeof item.type === "string"
        && item.loc.every((part: unknown) => typeof part === "string"
          || (typeof part === "number" && Number.isSafeInteger(part)))) {
        issues.push({ location: item.loc, type: item.type });
      }
    }
  }
  const seconds = retryAfter !== null && /^\d+$/.test(retryAfter) ? Number(retryAfter) : NaN;
  // Do not retain raw bodies, input/ctx, tokens or arbitrary server messages.
  return new ApiError("http", messages[status] ?? "Não foi possível concluir a operação.", status,
    issues, Number.isSafeInteger(seconds) ? seconds : undefined);
}
