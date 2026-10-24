import { proxyControlApi } from "../_proxy.js";

export const onRequest = context => proxyControlApi(context, "DELIVERY_API_BASE_URL");

