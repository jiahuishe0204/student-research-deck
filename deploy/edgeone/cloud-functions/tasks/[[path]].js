import { proxyControlApi } from "../_proxy.js";

export const onRequest = context => proxyControlApi(context, "TASK_API_BASE_URL");

