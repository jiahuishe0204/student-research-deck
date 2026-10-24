import { proxyControlApi } from "../_proxy.js";

export const onRequest = context => proxyControlApi(context, "AUTH_API_BASE_URL");

