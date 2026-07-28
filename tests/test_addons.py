import unittest
from app import app, get_db

class TestCyberForgeAddons(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()
        
        # Ensure database tables exist
        conn = get_db()
        cursor = conn.cursor()
        # Seed test user if needed
        cursor.execute("INSERT OR IGNORE INTO users (id, username, email, password) VALUES (999, 'test_analyst', 'test@cyberforge.com', 'hashedpassword')")
        conn.commit()
        conn.close()

    def set_session(self):
        with self.client.session_transaction() as sess:
            sess['username'] = 'test_analyst'
            sess['user_id'] = 999
            sess['email'] = 'test@cyberforge.com'

    def test_scenario_engine_routes(self):
        self.set_session()
        # Test index page
        res = self.client.get("/scenario_engine")
        self.assertEqual(res.status_code, 200)
        
        # Test api scenarios list
        res = self.client.get("/api/scenarios")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_gamification_routes(self):
        self.set_session()
        # Test gamification hub
        res = self.client.get("/gamification")
        self.assertEqual(res.status_code, 200)
        
        # Test gamification stats profile api
        res = self.client.get("/api/gamification/profile")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_siem_center_routes(self):
        self.set_session()
        res = self.client.get("/siem_center")
        self.assertEqual(res.status_code, 200)
        
        res = self.client.get("/api/siem/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_ai_mentor_routes(self):
        self.set_session()
        res = self.client.get("/ai_mentor")
        self.assertEqual(res.status_code, 200)
        
        res = self.client.get("/api/mentor/recommendations")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")

    def test_report_center_routes(self):
        self.set_session()
        res = self.client.get("/report_center")
        self.assertEqual(res.status_code, 200)

if __name__ == "__main__":
    unittest.main()
