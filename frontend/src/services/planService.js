import axios from "axios";
import API_BASE_URL from "./api";

const API = API_BASE_URL;

// Fetches the live TalentNest plan catalog from the backend. Plan data
// (pricing, features, plan ids) intentionally lives on the backend
// (app/plan_catalog.py) rather than being hardcoded in the UI, so this is
// the only place the Plans page should get that data from.
export const getPlans = async () => {
  const response = await axios.get(`${API}/plans`);
  return response.data;
};
