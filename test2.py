@pytest.mark.asyncio
async def test_authenticate_user(mock_db):
    mock_result = MagicMock()
    mock_db.execute.return_value = mock_result
    test_user = Employee (username="test", hashed_password="test123")
    mock_result.scalar_one_or_none.return_value = test_user

    user = await authenticate_user (mock_db, username: "test", password: "test123")
    assert user is not None, "Пользователь должен быть найден"
    assert user.username == "test"

    user = await authenticate_user(mock_db, username: "test", password: "wrong_password")
    assert user is None, "Пользователь не должен быть аутентифицирован с неверным паролем"