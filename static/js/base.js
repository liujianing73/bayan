// 钯盐系统 基础脚本

document.addEventListener('DOMContentLoaded', function () {
    // CSRF Token 获取，供后续 AJAX 请求使用
    function getCookie(name) {
        var value = '; ' + document.cookie;
        var parts = value.split('; ' + name + '=');
        if (parts.length === 2) return parts.pop().split(';').shift();
    }
    window.getCsrfToken = function () {
        return getCookie('csrftoken');
    };
});
