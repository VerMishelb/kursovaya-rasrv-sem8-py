// Функция для проверки наличия токена
function isAuthenticated() {
    return localStorage.getItem('token') !== null;
}

// Функция для добавления токена к запросам
async function fetchWithAuth(url, options = {}) {
    if (!options.headers) {
        options.headers = {};
    }
    
    const token = localStorage.getItem('token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(url, options);
    
    // Если токен недействителен, перенаправляем на страницу входа
    if (response.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/login';
        return null;
    }
    
    return response;
}

// Функция выхода из системы
function logout() {
    localStorage.removeItem('token');
    window.location.href = '/login';
}

// Проверка авторизации на защищенных страницах
document.addEventListener('DOMContentLoaded', function() {
    const currentPath = window.location.pathname;
    const publicPaths = ['/', '/login'];
    
    if (!publicPaths.includes(currentPath) && !isAuthenticated()) {
        window.location.href = '/login';
    }
}); 