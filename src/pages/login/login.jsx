// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, {useEffect, useState} from 'react';
import Avatar from '@mui/material/Avatar';
import LoadingButton from '@mui/lab/LoadingButton';
import CssBaseline from '@mui/material/CssBaseline';
import TextField from '@mui/material/TextField';
import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Link from '@mui/material/Link';
import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import LockOutlinedIcon from '@mui/icons-material/LockOutlined';
import Typography from '@mui/material/Typography';
import Container from '@mui/material/Container';
import { createTheme, ThemeProvider } from '@mui/material/styles';
import { useAuth } from '../commons/use-auth';
import {useNavigate} from 'react-router-dom';
import { useLocalStorage } from "../commons/use-local-storage";
import StepLabel from '@mui/material/StepLabel';
import Step from '@mui/material/Step';
import Stepper from '@mui/material/Stepper';
import { useTranslation } from 'react-i18next';



function Copyright(props) {
  return (
    <Typography variant="body2" color="text.secondary" align="center" {...props}>
      {'Copyright © '}
      <Link color="inherit" href="">
        Model Hub
      </Link>{' '}
      {new Date().getFullYear()}
      {'.'}
    </Typography>
  );
}

const theme = createTheme({
  // palette: {
  //   primary: blue,
  //   secondary: deepPurple,
  // },  
});

const SignUpSteps = ({activeStep, t}) =>{
  const steps = [t('signup_step1'), t('signup_step2'), t('signup_step3')];

  return (
    <Stepper activeStep={activeStep} alternativeLabel>
  {steps.map((label) => (
    <Step key={label}>
      <StepLabel>{label}</StepLabel>
    </Step>
  ))}
</Stepper>
  )


}

const LoginPage = ()=>{
  const [username, setUsername] = useState('demo_user');
  const [password, setPassword] = useState('demo_user');
  return (
    <SignIn username={username} setUsername={setUsername} password={password} setPassword={setPassword}/>
  )
}

const SignUp = ({setSignType,username,setUsername,password,setPassword}) =>{
  const auth = useAuth();
  const { t } = useTranslation();
  const [,setLocalStoredCred] = useLocalStorage('chatbot-local-credentials',null)
  const [errorstate, setErrorState] = useState(false);
  const [errormsg, setErrMsg] = useState('');
  // const [username, setUsername] = useState();
  // const [password, setPassword] = useState();

  const [email, setEmail] = useState();
  const [activeStep, setActiveStep] = useState(0);
  const [confirmCode , setConfirmCode] = useState();
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const isAuthenticated = auth.user && auth.user.isAuthorized;
  useEffect(()=>{
        if(isAuthenticated){
            navigate('/chat');
        }
    },[navigate,isAuthenticated]);

  const handleSubmit = (event) => {
    event.preventDefault();
    setErrorState(false);
    setErrMsg('');
    const formdata = new FormData(event.currentTarget);
    if (activeStep === 0){
      if (!formdata.get('username') || !formdata.get('email')){
        setErrorState(true);
        setErrMsg(t('need_username_email'));
        return;
      }
      setLoading(true);
      auth.signup(formdata.get('username'),formdata.get('email'),formdata.get('password'))
      .then((data)=>{
        setLocalStoredCred({username:formdata.get('username'),
                      password:formdata.get('password'),
                     email:formdata.get('email')});
          console.log(data);
          setActiveStep(1);
          setLoading(false);
      })  
      .catch(error =>{ 
        console.log(error);
        setErrorState(true);
        setErrMsg(error.response?.data);
        setLoading(false);
      })
    }else if (activeStep === 1){
      if (!formdata.get('confirmcode')){
        setErrorState(true);
        setErrMsg(t('need_confirm_code'));
        return;
      }
      setLoading(true);
      auth.confirm_signup(formdata.get('username'),formdata.get('confirmcode'))
      .then((data)=>{
          console.log(data);
          setActiveStep(2);
          setLoading(false);
          setTimeout(()=>setSignType('signin'),2000);
      })  
      .catch(error =>{ 
        setErrorState(true);
        setErrMsg(error.response.data);
        setLoading(false);
      })

    }


  };

  return (
    <ThemeProvider theme={theme}>
      <Container component="main" maxWidth="xs" >
        <CssBaseline />
        <Box
          sx={{
            marginTop: 8,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          <Avatar sx={{ m: 1, bgcolor: 'warning.main' }}>
            <LockOutlinedIcon />
          </Avatar>
          <Typography component="h1" variant="h5">
            {t('sign_up')}
          </Typography>

          <Box component="form" onSubmit={handleSubmit} noValidate sx={{ mt: 1 }}>
          <FormControl sx={{width:360}}>
            <TextField
              error = {errorstate}
              margin="normal"
              required
              fullWidth
              id="username"
              label={t('username')}
              name="username"
              value ={username??''}
              onChange = {(event) => { setUsername(event.target.value);}}
              autoFocus
            />
            <TextField
              error = {errorstate}
              margin="normal"
              required
              fullWidth
              id="email"
              label={t('email')}
              name="email"
              type="email"
              value ={email??''}
              onChange = {(event) => { setEmail(event.target.value);}}
              // autoFocus
            />
            <TextField
              error = {errorstate}
              helperText ={errormsg}
              margin="normal"
              required
              fullWidth
              name="password"
              label={t('password')}
              type="password"
              id="password"
              value ={password??''}
              onChange = {(event) => { setPassword(event.target.value);}}
              autoComplete="current-password"
            />
            {activeStep?
              <TextField
              error = {errorstate}
              helperText ={errormsg}
              margin="normal"
              required
              fullWidth
              name="confirmcode"
              label={t('confirm_code')}
              id="confirmcode"
              value ={confirmCode??''}
              onChange = {(event) => { setConfirmCode(event.target.value);}}
            />:<div/>

            }
            <SignUpSteps activeStep={activeStep} t={t}/>
            {
              activeStep === 0?
              <LoadingButton
              type="submit"
              loading = {loading}
              fullWidth
              variant="contained"
              color='secondary'
              sx={{ mt: 3, mb: 2,}}
            >
              {t('sign_up')}
            </LoadingButton>
            :
            <LoadingButton
              type="submit"
              loading = {loading}
              fullWidth
              variant="contained"
              color='warning'
              sx={{ mt: 3, mb: 2,}}
            >
              {t('confirm')}
            </LoadingButton>
            }

            <Grid container>
              <Grid item xs>
                <Link href="#" variant="body2">
                  {t('forgot_password')}
                </Link>
              </Grid>
              <Grid item>
                <Link href="#" variant="body2" onClick={()=>setSignType('signin')}>
                  {t('already_have_account')}
                </Link>
              </Grid>
            </Grid>
            </FormControl>
          </Box>

        </Box>
        <Copyright sx={{ mt: 8, mb: 4 }} />
      </Container>
    </ThemeProvider>
  );
}

const SignIn = ({username,setUsername,password,setPassword}) => {
  const auth = useAuth();
  const { t } = useTranslation();
  const [checked, setChecked] = useState(false);
  const [local_stored_crediential,setLocalStoredCred] = useLocalStorage('modelhub_login_credentials',null)
  const [errorstate, setErrorState] = useState(false);
  const [errormsg, setErrMsg] = useState('');
  // const [username, setUsername] = useState();
  // const [password, setPassword] = useState();
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const isAuthenticated = auth.user && auth.user.isAuthorized;
  useEffect(()=>{
        if(isAuthenticated){
            navigate('/chat');
        }
    },[navigate,isAuthenticated]);

  useEffect(()=>{
    setChecked(local_stored_crediential?.checked);
    if (local_stored_crediential?.checked) {
      setUsername(local_stored_crediential.username);
      setPassword(local_stored_crediential.password);
    }
  },[]);
  // useEffect(()=>{
  //   if (local_stored_crediential) {
  //       setChecked(local_stored_crediential.checked);
  //       if (local_stored_crediential.checked) {
  //         setUsername(local_stored_crediential.username);
  //         setPassword(local_stored_crediential.password);
  //       }
  //   }
  // },[checked,local_stored_crediential]);
  const handleSubmit = (event) => {
    event.preventDefault();
    setLoading(true);
    setErrorState(false);
    setErrMsg('');
    const formdata = new FormData(event.currentTarget);
    auth.signin(formdata.get('username'),formdata.get('password'))
    .then((data)=>{
      setLocalStoredCred({username:formdata.get('username'),
                    password:formdata.get('password'),
                   checked:checked});
        // console.log(data);
        if (!(data?data.isAuthorized:false)){
          setErrorState(true);
          setErrMsg(data.error);
        }
        setLoading(false);
    })  
    .catch(error =>{ 
      setErrorState(true);
      setErrMsg(error.response?.data);
      setLoading(false);
    })

  };

  return (
    <ThemeProvider theme={theme}>
      <Container component="main" maxWidth="xs" >
        <CssBaseline />
        <Box
          sx={{
            marginTop: 8,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          <Avatar sx={{ m: 1, bgcolor: 'warning.main' }}>
            <LockOutlinedIcon />
          </Avatar>
          <Typography component="h1" variant="h5">
            {t('sign_in')}
          </Typography>

          <Box component="form" onSubmit={handleSubmit} noValidate sx={{ mt: 1 }}>
          <FormControl sx={{width:360}}>
            <TextField
              error = {errorstate}
              margin="normal"
              required
              fullWidth
              id="username"
              label={t('username')}
              name="username"
              value ={username??''}
              onChange = {(event) => { setUsername(event.target.value);}}
              autoFocus
            />
            <TextField
              error = {errorstate}
              helperText ={errormsg}
              margin="normal"
              required
              fullWidth
              name="password"
              label={t('password')}
              type="password"
              id="password"
              value ={password??''}
              onChange = {(event) => { setPassword(event.target.value);}}
              autoComplete="current-password"
            />
            <FormControlLabel
              control={<Checkbox
                checked={checked}
                onChange={(event) =>{
                  setChecked(event.target.checked);
                  setLocalStoredCred({checked:event.target.checked});
                }}
               color="primary" />}
              label={t('remember_me')}
            />
            <LoadingButton
              type="submit"
              loading = {loading}
              fullWidth
              variant="contained"
              sx={{ mt: 3, mb: 2}}
            >
              {t('sign_in')}
            </LoadingButton>
            {/* <Button
             fullWidth
              variant="contained"
              sx={{ mt: 0.5, mb: 0.5}}
              color = "secondary"
              onClick={()=>setSignType('signup')}
              >
              {"Sign Up"}
            </Button>
            <Grid container>
              <Grid item xs>
                <Link href="#" variant="body2">
                  Forgot password?
                </Link>
              </Grid>
              <Grid item>
                <Link href="#" variant="body2" onClick={()=>setSignType('signup')}>
                  {"Don't have an account? Sign Up"}
                </Link>
              </Grid>
            </Grid> */}
            </FormControl>
          </Box>

        </Box>
        <Copyright sx={{ mt: 8, mb: 4 }} />
      </Container>
    </ThemeProvider>
  );
}

export default LoginPage;