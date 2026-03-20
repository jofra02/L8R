import axios from "axios";

const API_BASE = "/api/v1";

const client = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
});

client.interceptors.request.use((config) => {
  const key = localStorage.getItem("api_key");
  if (key) {
    config.headers.Authorization = `Bearer ${key}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("api_key");
      localStorage.removeItem("auth_context");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export default client;
