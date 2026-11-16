import React,{useState} from 'react';
export function AuthScreen({auth}){
  const [mode,setMode]=useState('login');const [username,setUsername]=useState('');const [password,setPassword]=useState('');const [error,setError]=useState('');
  async function submit(e){e.preventDefault();setError('');try{await auth.authenticate(mode,username,password)}catch(e){setError(e.message)}}
  return <main className="auth-layout"><section className="auth-panel"><div className="brand"><span className="brand-mark">А</span><span>альфа<span className="brand-light">курс</span></span></div>
    <h1>{mode==='login'?'Войти в профиль':'Создать аккаунт'}</h1><p>Войдите, чтобы сохранять интересы и историю обучения.</p>
    <form onSubmit={submit} className="auth-form"><label>Логин<input autoComplete="username" pattern="[A-Za-z0-9_.-]{3,64}" title="От 3 до 64 символов: латиница, цифры, точка, подчёркивание или дефис" minLength={3} maxLength={64} required value={username} onChange={e=>setUsername(e.target.value)}/></label>
    <label>Пароль<input type="password" autoComplete={mode==='login'?'current-password':'new-password'} minLength={10} maxLength={128} required value={password} onChange={e=>setPassword(e.target.value)}/></label>
    {(error||auth.error)&&<p className="notice" role="alert">{error||auth.error}</p>}
    <button className="primary" type="submit" disabled={auth.status==='loading'}>{auth.status==='loading'?'Подключаемся...':mode==='login'?'Войти':'Зарегистрироваться'}</button></form>
    <button className="auth-switch" onClick={()=>{setError('');setMode(mode==='login'?'register':'login')}}>{mode==='login'?'Нет аккаунта? Зарегистрироваться':'Уже есть аккаунт? Войти'}</button>
    <p className="auth-note">Это отдельная учётная запись сервиса. Используйте уникальный пароль; сессия сохраняется до закрытия вкладки.</p>
  </section></main>;
}
