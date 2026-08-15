import axios from "axios";

export const apiBaseURL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export const apiClient = axios.create({
  baseURL: apiBaseURL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

export default apiClient;
