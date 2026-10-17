from __future__ import annotations

import io
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import app as bytequest_app
from app import create_app, make_quest, run_code_in_sandbox, validate_code


def text_pdf(text: str) -> bytes:
    stream = f"BT /F1 16 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(pdf)


class ByteQuestApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.sqlite3"
        self.app = create_app({"TESTING": True, "DATABASE": str(database)})
        self.client = self.app.test_client()
        self.teacher = self.app.test_client()
        self.register(self.client, "student@example.com", "student")
        self.register(self.teacher, "teacher@example.com", "teacher")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def register(self, client, email: str, role: str) -> None:
        response = client.post(
            "/api/auth/register",
            json={"email": email, "name": role.title(), "password": "classroom-pass", "role": role},
        )
        self.assertEqual(response.status_code, 201, response.get_json())

    def publish_loop_quest(self) -> str:
        response = self.teacher.post(
            "/api/quests/drafts",
            data={"pdf": (io.BytesIO(text_pdf("Python for loops and range")), "loops.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        draft = response.get_json()
        self.assertEqual(draft["topic"], "for loops")
        self.assertEqual(draft["question_count"], 4)
        self.assertNotIn("answer", draft["questions"][0])

        publish = self.teacher.post(f"/api/quests/{draft['id']}/publish")
        self.assertEqual(publish.status_code, 200)
        return draft["id"]

    def test_teacher_upload_publish_student_quiz_and_persistent_xp(self) -> None:
        quest_id = self.publish_loop_quest()
        bootstrap = self.client.get("/api/bootstrap").get_json()
        self.assertEqual(bootstrap["quest"]["id"], quest_id)
        self.assertEqual(bootstrap["student"]["xp"], 0)

        started = self.client.post(f"/api/quests/{quest_id}/attempts")
        self.assertEqual(started.status_code, 201)
        attempt = started.get_json()
        attempt_id = attempt["attempt_id"]
        self.assertEqual(len(attempt["questions"]), 4)
        self.assertNotIn("answer", attempt["questions"][0])

        for question_index, answer_index in enumerate((0, 1, 2, 0)):
            result = self.client.post(
                f"/api/attempts/{attempt_id}/answers",
                json={"question_index": question_index, "answer_index": answer_index},
            )
            self.assertEqual(result.status_code, 200, result.get_json())
            self.assertTrue(result.get_json()["correct"])

        with patch("app.run_code_in_sandbox", return_value={"output": "1\n2\n3\n4\n5\n", "exit_code": 0}):
            code_result = self.client.post(
                f"/api/attempts/{attempt_id}/challenge",
                json={"code": "for number in range(1, 6):\n    print(number)"},
            )
        self.assertEqual(code_result.status_code, 200, code_result.get_json())
        self.assertTrue(code_result.get_json()["passed"])
        self.assertEqual(code_result.get_json()["output"], "1\n2\n3\n4\n5\n")
        self.assertEqual(code_result.get_json()["xp_total"], 150)

        persisted = self.client.get("/api/bootstrap").get_json()
        self.assertEqual(persisted["student"]["xp"], 150)
        self.assertEqual(persisted["student"]["streak"], 1)
        self.assertEqual(persisted["student"]["completed_today"], 1)
        self.assertEqual(persisted["activities"][0]["xp_earned"], 150)
        self.assertEqual(persisted["leaderboard"][0]["xp"], 150)

    def test_quiz_enforces_order_and_challenge_requires_quiz_completion(self) -> None:
        quest_id = self.publish_loop_quest()
        attempt = self.client.post(f"/api/quests/{quest_id}/attempts").get_json()
        attempt_id = attempt["attempt_id"]

        out_of_order = self.client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"question_index": 1, "answer_index": 0},
        )
        self.assertEqual(out_of_order.status_code, 409)

        premature_challenge = self.client.post(
            f"/api/attempts/{attempt_id}/challenge",
            json={"code": "for n in range(3):\n    print(n)"},
        )
        self.assertEqual(premature_challenge.status_code, 409)

        first_answer = self.client.post(
            f"/api/attempts/{attempt_id}/answers",
            json={"question_index": 0, "answer_index": 1},
        )
        self.assertFalse(first_answer.get_json()["correct"])
        self.assertEqual(first_answer.get_json()["xp_total"], 0)

    def test_topic_generation_and_python_validation(self) -> None:
        self.assertEqual(make_quest("Python functions and parameters", "lesson.pdf")["topic"], "functions")
        self.assertEqual(make_quest("Python if statements and boolean values", "lesson.pdf")["topic"], "conditionals")
        self.assertEqual(make_quest("while loops and iteration", "lesson.pdf")["topic"], "while loops")
        self.assertEqual(make_quest("JavaScript loops and iteration", "lesson.pdf", "javascript")["language"], "javascript")

        valid, _ = validate_code("for loops", "for item in range(3):\n    print(item)")
        self.assertTrue(valid)
        valid, message = validate_code("for loops", "for item in range(3)\n    print(item)")
        self.assertFalse(valid)
        self.assertIn("syntax error", message.lower())

    def test_upload_rejects_non_pdf_and_image_only_pdf(self) -> None:
        non_pdf = self.teacher.post(
            "/api/quests/drafts",
            data={"pdf": (io.BytesIO(b"not a pdf"), "lesson.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(non_pdf.status_code, 400)

        image_only = self.teacher.post(
            "/api/quests/drafts",
            data={"pdf": (io.BytesIO(text_pdf(" ")), "scan.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(image_only.status_code, 400)

    def test_login_and_role_permissions(self) -> None:
        unauthorized = self.app.test_client().get("/api/bootstrap")
        self.assertEqual(unauthorized.status_code, 401)

        wrong_role = self.client.post(
            "/api/quests/drafts",
            data={"pdf": (io.BytesIO(text_pdf("Python loops")), "loops.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(wrong_role.status_code, 403)

        teacher_bootstrap = self.teacher.get("/api/bootstrap")
        self.assertEqual(teacher_bootstrap.status_code, 200)
        self.assertIsNone(teacher_bootstrap.get_json()["student"])

        logged_out = self.client.post("/api/auth/logout")
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(self.client.get("/api/bootstrap").status_code, 401)
        signed_in = self.client.post(
            "/api/auth/login",
            json={"email": "STUDENT@example.com", "password": "classroom-pass", "role": "student"},
        )
        self.assertEqual(signed_in.status_code, 200)
        self.assertEqual(self.client.get("/api/bootstrap").status_code, 200)

    def test_selected_language_is_stored_with_published_quest(self) -> None:
        response = self.teacher.post(
            "/api/quests/drafts",
            data={
                "pdf": (io.BytesIO(text_pdf("JavaScript loops and iteration")), "loops.pdf"),
                "language": "javascript",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        draft = response.get_json()
        self.assertEqual(draft["language"], "javascript")
        self.assertEqual(draft["expected_output"], "1\n2\n3\n4\n5")
        self.assertEqual(self.teacher.post(f"/api/quests/{draft['id']}/publish").status_code, 200)
        attempt = self.client.post(f"/api/quests/{draft['id']}/attempts").get_json()
        self.assertEqual(attempt["quest"]["language"], "javascript")

    def test_challenge_output_must_match_expected_output(self) -> None:
        quest_id = self.publish_loop_quest()
        attempt = self.client.post(f"/api/quests/{quest_id}/attempts").get_json()
        for question_index, answer_index in enumerate((0, 1, 2, 0)):
            self.client.post(
                f"/api/attempts/{attempt['attempt_id']}/answers",
                json={"question_index": question_index, "answer_index": answer_index},
            )
        with patch("app.run_code_in_sandbox", return_value={"output": "wrong\n", "exit_code": 0}):
            response = self.client.post(
                f"/api/attempts/{attempt['attempt_id']}/challenge",
                json={"code": "console.log('wrong')"},
            )
        self.assertFalse(response.get_json()["passed"])
        self.assertEqual(response.get_json()["output"], "wrong\n")

    def test_sandbox_refuses_to_execute_without_docker(self) -> None:
        with patch.object(bytequest_app.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Docker Desktop is required"):
                run_code_in_sandbox("python", "print('unsafe')")


if __name__ == "__main__":
    unittest.main()
