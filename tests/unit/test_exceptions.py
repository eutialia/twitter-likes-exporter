import pytest

from likes_archive.exceptions import MediaNotFound, TokenExpiredError


class TestTokenExpiredError:
    def test_is_exception_subclass(self):
        assert issubclass(TokenExpiredError, Exception)

    def test_carries_status_code(self):
        exc = TokenExpiredError(status_code=401)
        assert exc.status_code == 401

    def test_str_includes_status_code(self):
        exc = TokenExpiredError(status_code=403)
        assert "403" in str(exc)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(TokenExpiredError) as exc_info:
            raise TokenExpiredError(status_code=401)
        assert exc_info.value.status_code == 401


class TestMediaNotFound:
    def test_is_exception_subclass(self):
        assert issubclass(MediaNotFound, Exception)

    def test_carries_key(self):
        exc = MediaNotFound(key="images/tweets/abc.jpg")
        assert exc.key == "images/tweets/abc.jpg"

    def test_str_includes_key(self):
        exc = MediaNotFound(key="images/avatars/999.jpg")
        assert "images/avatars/999.jpg" in str(exc)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(MediaNotFound) as exc_info:
            raise MediaNotFound(key="videos/tweets/clip.mp4")
        assert exc_info.value.key == "videos/tweets/clip.mp4"
