import { proxyControlApi } from "../_proxy.js";

export const onRequest = context => proxyControlApi(context, "INTENT_API_BASE_URL", 110_000);
