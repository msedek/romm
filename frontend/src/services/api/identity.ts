import api from "@/services/api";

export const identityApi = api;

async function logout() {
  return api.post("/logout", {});
}

export default {
  logout,
};
