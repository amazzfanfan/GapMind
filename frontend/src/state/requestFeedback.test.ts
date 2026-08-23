import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { requestErrorMessage } from "./requestFeedback";

describe("request feedback", () => {
  it("keeps API envelope guidance", () => {
    const error = new AxiosError("bad gateway", undefined, undefined, undefined, {
      status: 400,
      statusText: "Bad Request",
      headers: new AxiosHeaders(),
      config: { headers: new AxiosHeaders() },
      data: { detail: { message: "请先选择目标课题。" } },
    });
    expect(requestErrorMessage(error)).toBe("请先选择目标课题。");
  });

  it("maps offline, timeout, and rate-limit errors to safe remediation", () => {
    expect(requestErrorMessage(new AxiosError("Network Error", "ERR_NETWORK")))
      .toBe("无法连接到本地服务，请确认后端（8000）及必要依赖已启动。");
    expect(requestErrorMessage(new AxiosError("timeout", "ECONNABORTED")))
      .toBe("请求超时，请确认本地服务仍在运行后重试。");
    const limited = new AxiosError("Too Many Requests", undefined, undefined, undefined, {
      status: 429,
      statusText: "Too Many Requests",
      headers: new AxiosHeaders(),
      config: { headers: new AxiosHeaders() },
      data: {},
    });
    expect(requestErrorMessage(limited)).toBe("请求过于频繁，请稍候再试。");
  });
});
