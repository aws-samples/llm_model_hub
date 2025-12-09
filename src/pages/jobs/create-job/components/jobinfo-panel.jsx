// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from 'react';
import {
  Container,
  Checkbox,
  ExpandableSection,
  Header,
  Input,
  RadioGroup,
  FormField,
  SpaceBetween,
  Select,
  Grid,
  Link,
  Multiselect,
  Toggle,
  Textarea,
  Box,
  StatusIndicator,
  Spinner,
  ColumnLayout,
} from '@cloudscape-design/components';
import { FT_OPTIONS, QUANT_OPTIONS, TRAINING_STAGES, TRAINING_PRECISION, OPTMIZERS, INSTANCE_TYPES, BOOSTER_OPTIONS, DEEPSPEED,FORMAT_PROMPT_OPTIONS } from '../form-config';
import validateField from '../form-validation-config';
import { remotePost } from '../../../../common/api-gateway';
import { S3Selector } from './output-path';
import { JsonEditor,PythonEditor } from './code-editor';
import { t } from 'i18next';


// SpotPriceInfo component to display spot price and interruption rate
const SpotPriceInfo = ({ instanceType, useSpot, readOnly }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [priceData, setPriceData] = useState(null);
  const [riskData, setRiskData] = useState(null);

  useEffect(() => {
    // Only fetch if we have an instance type and spot is enabled
    if (!instanceType || !useSpot || readOnly) {
      setPriceData(null);
      setRiskData(null);
      return;
    }

    const fetchSpotInfo = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch spot price history
        const priceResponse = await remotePost(
          { instance_types: [instanceType], days: 7 },
          'spot_price_history'
        );

        if (priceResponse?.response?.instance_types?.[instanceType]) {
          setPriceData(priceResponse.response.instance_types[instanceType]);
        } else {
          setPriceData(null);
        }

        // Fetch interruption rate
        const riskResponse = await remotePost(
          { instance_type: instanceType },
          'spot_interruption_rate'
        );

        if (riskResponse?.response) {
          setRiskData(riskResponse.response);
        } else {
          setRiskData(null);
        }
      } catch (err) {
        console.error('Error fetching spot price info:', err);
        setError(err.message || t('spot_price_error'));
      } finally {
        setLoading(false);
      }
    };

    fetchSpotInfo();
  }, [instanceType, useSpot, readOnly]);

  // Don't show anything if spot is not enabled or no instance type selected
  if (!useSpot || readOnly) {
    return null;
  }

  if (!instanceType) {
    return (
      <Box color="text-status-inactive" padding={{ top: 's' }}>
        <StatusIndicator type="info">{t('spot_select_instance')}</StatusIndicator>
      </Box>
    );
  }

  if (loading) {
    return (
      <Box padding={{ top: 's' }}>
        <SpaceBetween direction="horizontal" size="xs">
          <Spinner size="normal" />
          <span>{t('spot_price_loading')}</span>
        </SpaceBetween>
      </Box>
    );
  }

  if (error) {
    return (
      <Box padding={{ top: 's' }}>
        <StatusIndicator type="error">{error}</StatusIndicator>
      </Box>
    );
  }

  if (!priceData?.available) {
    return (
      <Box padding={{ top: 's' }}>
        <StatusIndicator type="warning">{t('spot_not_available')}</StatusIndicator>
      </Box>
    );
  }

  const getRiskStatusType = (riskLevel) => {
    switch (riskLevel) {
      case 'low':
        return 'success';
      case 'medium':
        return 'warning';
      case 'high':
        return 'error';
      default:
        return 'info';
    }
  };

  const getRiskLabel = (riskLevel) => {
    switch (riskLevel) {
      case 'low':
        return t('spot_risk_low');
      case 'medium':
        return t('spot_risk_medium');
      case 'high':
        return t('spot_risk_high');
      default:
        return t('spot_risk_unknown');
    }
  };

  return (
    <Box padding={{ top: 's' }}>
      <ExpandableSection headerText={t('spot_price_info')} variant="footer" defaultExpanded>
        <SpaceBetween size="s">
          <ColumnLayout columns={2} variant="text-grid">
            <div>
              <Box variant="awsui-key-label">{t('spot_current_price')}</Box>
              <Box variant="p">
                ${priceData.availability_zones?.[0]?.current_price?.toFixed(4) || 'N/A'}/hr
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_price_range')}</Box>
              <Box variant="p">
                ${priceData.min_price?.toFixed(4)} - ${priceData.max_price?.toFixed(4)}/hr
              </Box>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_volatility')}</Box>
              <Box variant="p">{priceData.price_volatility?.toFixed(1)}%</Box>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_risk_level')}</Box>
              <StatusIndicator type={getRiskStatusType(riskData?.risk_level)}>
                {getRiskLabel(riskData?.risk_level)}
              </StatusIndicator>
            </div>
            <div>
              <Box variant="awsui-key-label">{t('spot_recommended_az')}</Box>
              <Box variant="p">{priceData.recommended_az || 'N/A'}</Box>
            </div>
          </ColumnLayout>
          {riskData?.risk_description && (
            <Box variant="small" color="text-body-secondary">
              {riskData.risk_description}
            </Box>
          )}
        </SpaceBetween>
      </ExpandableSection>
    </Box>
  );
};


function AdvancedConfigs({ onChange, readOnly, data, setData }) {
  return (
    <SpaceBetween size="l">
      <ExpandableSection headerText={`Extra ${t('configurations')}`} variant="footer">
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("warmup_steps")}
            description={t("warmup_steps_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.warmup_steps : data.warmup_steps}
              onChange={({ detail: { value } }) => onChange('warmup_steps', value)}
            />
          </FormField>
          <FormField
            label={t("logging_steps")}
            description={t("logging_steps_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.logging_steps : data.logging_steps}
              onChange={({ detail: { value } }) => onChange('logging_steps', value)}
            />
          </FormField>
        </Grid>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("save_steps")}
            description={t("save_steps_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.save_steps : data.save_steps}
              onChange={({ detail: { value } }) => onChange('save_steps', value)}
            />
          </FormField>
          <FormField
            label={t("optimizer")}
            description={t("optimizer_desc")}
            stretch={false}
          >
            <SelectOptimizer readOnly={readOnly} data={data} setData={setData} />
          </FormField>
        </Grid>

      </ExpandableSection>
      <ExpandableSection headerText={`Lora ${t('configurations')}`} variant="footer">
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("lora_rank")}
            description={t("lora_rank_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.lora_rank : data.lora_rank}
              onChange={({ detail: { value } }) => onChange('lora_rank', value)}
            />
          </FormField>
          <FormField
            label={t("lora_alpha")}
            description={t("lora_alpha_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.lora_alpha : data.lora_alpha}
              onChange={({ detail: { value } }) => onChange('lora_alpha', value)}
            />
          </FormField>
        </Grid>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("lora_target_modules")}
            description={t("lora_target_modules_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.lora_target_modules : data.lora_target_modules}
              onChange={({ detail: { value } }) => onChange('lora_target_modules', value)}
            />
          </FormField>
        </Grid>
      </ExpandableSection>
      <ExpandableSection headerText={`RLHF ${t('configurations')}`} variant="footer">
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("rlhf_beta")}
            description={t("rlhf_beta_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.pref_beta : data.pref_beta}
              onChange={({ detail: { value } }) => onChange('pref_beta', value)}
            />
          </FormField>
          <FormField
            label={t("rlhf_ftx_gamma")}
            description={t("rlhf_ftx_gamma_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.pref_ftx : data.pref_ftx}
              onChange={({ detail: { value } }) => onChange('pref_ftx', value)}
            />
          </FormField>
        </Grid>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("rlhf_loss_type")}
            stretch={false}
          >
            <SelectLossType data={data} setData={setData} readOnly={readOnly} />
          </FormField>
        </Grid>
      </ExpandableSection>
    </SpaceBetween>
  );
}

function DeepSpeedConfigs({ onChange, readOnly, data, setData }) {
  return (
    <SpaceBetween size="l">
      <ExpandableSection headerText={t("deepspeed_config")} variant="footer" expanded>
        <Grid
          gridDefinition={[{ colspan: { default: 6, xxs: 4 } }, { colspan: { default: 6, xxs: 4 } }]}
        >
          <FormField
            label={t("deepspeed_stage")}
            description={t("deepspeed_stage_desc")}
            stretch={false}
          >
            <RadioGroup
              items={DEEPSPEED}
              value={readOnly ? data.job_payload?.deepspeed : data.deepspeed}
              onChange={({ detail: { value } }) => onChange('deepspeed', value)}
              readOnly={readOnly}
            />
          </FormField>
        </Grid>
      </ExpandableSection>

    </SpaceBetween>
  );
}

const SelectPromptTemplate = ({ data, setData, readOnly, refs }) => {
  const [loadStatus, setLoadStatus] = useState("loading");
  const [items, setItems] = useState([]);
  // const initState = data.job_payload ? { label: data.job_payload.prompt_template, value: data.job_payload.prompt_template } : {};
  const [selectOption, setSelectOption] = useState({});
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.prompt_template, value: data.job_payload.prompt_template });
      setData({ prompt_template: data.job_payload.prompt_template })
    }
  }, [data.job_payload]);
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'prompt_template' }, 'get_factory_config');
      const items = data.response.body.map((it) => ({
        prompt_template: it,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
  return (
    <Select
      statusType={loadStatus}
      onLoadItems={handleLoadItems}
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ prompt_template: detail.selectedOption.value })
      }}
      options={items.map(({ prompt_template }) => ({
        label: prompt_template,
        value: prompt_template,
      }))}
      selectedAriaLabel="Selected"
      ref={refs.prompt_template}
    />
  )
}


const SelectModelName = ({ data, setData, readOnly, refs }) => {
  const [loadStatus, setLoadStatus] = useState("loading");
  const [items, setItems] = useState([]);
  const [selectOption, setSelectOption] = useState({});
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.model_name, value: data.job_payload.model_name })
      setData({ model_name: data.job_payload.model_name })
    }
  }, [data.job_payload])
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'model_name' }, 'get_factory_config');
      const items = data.response.body.map((it) => ({
        model_name: it.model_name,
        model_path: it.model_path,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
  return (
    <Select
      statusType={loadStatus}
      onLoadItems={handleLoadItems}
      disabled={readOnly}
      selectedOption={selectOption}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ model_name: detail.selectedOption.value })
      }}
      options={items.map(({ model_name, model_path }) => ({
        label: model_name,
        value: model_path,
        tags: [model_path]
      }))}
      selectedAriaLabel="Selected"
      ref={refs.model_name}
    />
  )
}

const SelectDatasets = ({ data, setData, readOnly, refs }) => {
  const [loadStatus, setLoadStatus] = useState("loading");
  const [items, setItems] = useState([]);

  const initState = data.job_payload && data.job_payload.dataset ? data.job_payload.dataset.map(item => ({
    label: item, value: item
  })) : []
  // const [selectOption, setSelectOption] = useState(initState);

  const [selectedOptions, setSelectOptions] = useState(initState);
  const handleLoadItems = async ({
    detail: { filteringText, firstPage, samePage },
  }) => {
    setLoadStatus("loading");
    try {
      const resp = await remotePost({ config_name: 'dataset', stage: data.stage }, 'get_factory_config');
      const items = resp.response.body.map((it) => ({
        dataset: it,
      }));
      setItems(items);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };
  useEffect(() => {
    setSelectOptions(initState);
    setLoadStatus("pending");
    setItems([]);
  }, [data.stage])

  return (
    <Multiselect
      statusType={loadStatus}
      onLoadItems={handleLoadItems}
      disabled={readOnly}
      selectedOptions={selectedOptions}
      onChange={({ detail }) => {
        setSelectOptions(detail.selectedOptions);
        setData({ dataset: detail.selectedOptions.map(it => it.value) })
      }}
      options={items.map(({ dataset }) => ({
        label: dataset,
        value: dataset,
      }))}
      selectedAriaLabel="Selected"
      ref={refs.dataset}
    />
  )
}

const SelectStage = ({ data, setData, readOnly, refs }) => {

  const initState = TRAINING_STAGES.filter(item => data.job_payload?.stage === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : {});
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ stage: detail.selectedOption.value })
      }}
      options={TRAINING_STAGES}
      selectedAriaLabel="Selected"
      ref={refs.stage}
    />
  )
}

const SelectOptimizer = ({ data, setData, readOnly, refs }) => {
  const initState = OPTMIZERS.filter(item => data.job_payload?.optimizer === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : OPTMIZERS[0]);
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ optimizer: detail.selectedOption.value })
      }}
      options={OPTMIZERS}
      selectedAriaLabel="Selected"
    />
  )
}

const SelectInstanceType = ({ data, setData, readOnly, refs }) => {
  // const initState = INSTANCE_TYPES.filter(item => data.job_payload?.instance_type === item.value)
  const [selectOption, setSelectOption] = useState([]);
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.instance_type, value: data.job_payload.instance_type })
      setData({ instance_type: data.job_payload.instance_type })
    }
  }, [data.job_payload])
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ instance_type: detail.selectedOption.value })
      }}
      options={INSTANCE_TYPES}
      selectedAriaLabel="Selected"
      ref={refs.instance_type}
    />
  )
}

const SelectLossType = ({ data, setData, readOnly }) => {
  // const initState = INSTANCE_TYPES.filter(item => data.job_payload?.instance_type === item.value)
  const [selectOption, setSelectOption] = useState({ label: 'sigmoid', value: 'sigmoid' });
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.pref_loss, value: data.job_payload.pref_loss })
      setData({ pref_loss: data.job_payload.pref_loss })
    }
  }, [data.job_payload])
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ pref_loss: detail.selectedOption.value })
      }}
      options={[
        { label: 'sigmoid', value: 'sigmoid' },
      ]}
      selectedAriaLabel="Selected"
    />
  )
}

const SelectTrainingPrecision = ({ data, setData, readOnly, refs }) => {

  const initState = TRAINING_PRECISION.filter(item => data.job_payload?.training_precision === item.value)
  const [selectOption, setSelectOption] = useState(initState.length ? initState[0] : TRAINING_PRECISION[0]);
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ training_precision: detail.selectedOption.value })
      }}
      options={TRAINING_PRECISION}
      selectedAriaLabel="Selected"
    />
  )
}

const SelectFormatPromptType= ({ data, setData, readOnly, refs }) => {
  const [selectOption, setSelectOption] = useState({ label: 'math', value: 'math' });
  // const [promptContent, setPromptContent] = useState(FORMAT_PROMPT_OPTIONS['math'] );
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.format_prompt_type, value: data.job_payload.format_prompt_type });
      setData({ format_prompt_type: data.job_payload.format_prompt_type });
      
    }
  }, [data.job_payload])
  return (
    <SpaceBetween size="l">
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ format_prompt_type: detail.selectedOption.value });
        if (detail.selectedOption.value !== 'customize'){
          setData({ format_prompt: FORMAT_PROMPT_OPTIONS[detail.selectedOption.value] });
        }else{
          setData({ format_prompt: data.format_prompt});
        }
      }}
      options={[
        { label: 'math', value: 'math' },
        { label: 'r1v', value: 'r1v' },
        { label: 'customize', value: 'customize' }
      ]}
      selectedAriaLabel="Selected"
    />

    <Textarea 
      readOnly={readOnly}
      rows = {5}
      value={readOnly ? data.job_payload?.format_prompt : data.format_prompt}
      onChange={(event) => {
        setData({format_prompt:event.detail.value});
        // setPromptContent(event.detail.value);
      }}
      />
 </SpaceBetween>
  )
}


const SelectRewardFunction = ({ data, setData, readOnly, refs }) => {
  const [selectOption, setSelectOption] = useState({ label: 'math:compute_score', value: 'math:compute_score' });
  useEffect(() => {
    if (data.job_payload) {
      setSelectOption({ label: data.job_payload.reward_function, value: data.job_payload.reward_function })
      setData({ reward_function: data.job_payload.reward_function })
    }
  }, [data.job_payload])
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData({ reward_function: detail.selectedOption.value })
      }}
      options={[
        { label: 'math:compute_score', value: 'math:compute_score' },
        { label: 'r1v:compute_score', value: 'r1v:compute_score' },
        { label: 'customize', value: 'customize' }
      ]}
      selectedAriaLabel="Selected"
    />
  )
}

const EasyR1JobSetting = ({ validation,
  onChange,
  readOnly,
  data,
  errors,
  setData,
  setErrors,
  refs }) =>{

    //bypass the prompt_template
    useEffect(()=>{
      setData({prompt_template:'dummy'});
    },[]);

    // Set default clip ratio values based on stage
    useEffect(() => {
      if (!readOnly && data.stage) {
        if (data.stage === 'dapo') {
          setData({ clip_ratio_low: '0.2' });
          setData({ clip_ratio_high: '0.28' });
        } else if (data.stage === 'gspo') {
          setData({ clip_ratio_low: '3e-4' });
          setData({ clip_ratio_high: '4e-4' });
        } else if (data.stage === 'cispo') {
          setData({ clip_ratio_low: '0' });
          setData({ clip_ratio_high: '4' });
        }
      }
    }, [data.stage]);
    return (<SpaceBetween size="xl" direction="vertical">
            <Container
              header={<Header variant="h2">{t('training_job_settings')}</Header>}
            >
              <SpaceBetween size="l">
                <FormField
                  label={t('model_name')}
                  stretch={false}
                  description={t("select_model")}
                  errorText={errors.model_name}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <SelectModelName data={data} setData={setData} readOnly={readOnly} refs={refs} />
                </FormField>
                <FormField
                  label={t("use_existing_model_weight")}
                  stretch={false}
                  description={t("use_existing_model_weight_desc")}
                  errorText={errors.s3_model_path}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <S3Selector
                    readOnly={readOnly}
                    objectsIsItemDisabled={(item) => !item.IsFolder}
                    setOutputPath={(value) => setData({ s3_model_path: value })}
                    outputPath={readOnly ? data.job_payload?.s3_model_path : data.s3_model_path} />
                </FormField>
                <FormField
                  label={t("use_existing_checkpoint")}
                  stretch={false}
                  description={t("use_existing_checkpoint_desc")}
                  errorText={errors.s3_checkpoint}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <S3Selector
                    readOnly={readOnly}
                    objectsIsItemDisabled={(item) => !item.IsFolder}
                    setOutputPath={(value) => setData({ s3_checkpoint: value })}
                    outputPath={readOnly ? data.job_payload?.s3_checkpoint : data.s3_checkpoint} />
                </FormField>
                <FormField
                  label={t('finetuning_method')}
                  description={t("choose_ft_method_grpo")}
                  stretch={true}
                >
                  <RadioGroup
                    items={FT_OPTIONS}
                    readOnly={readOnly}
                    value={readOnly ? data.job_payload?.finetuning_method : data.finetuning_method}
                    onChange={({ detail: { value } }) => onChange('finetuning_method', value)}
                    ref={refs.finetuning_method}
                  />
                </FormField>
                <FormField
                  label={t("max_job_run_hour")}
                  description={t("max_job_run_hour_desc")}
                  stretch={false}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload?.max_job_run_hour : data.max_job_run_hour}
                    onChange={({ detail: { value } }) => onChange('max_job_run_hour', value)}
                  />
                </FormField>
              </SpaceBetween>
            </Container>
            <Container
              header={<Header variant="h2">{t('datasets_settings')}</Header>}
            >
              <SpaceBetween size="l">
                <FormField
                  label={t("training_data_s3")}
                  stretch={false}
                  description={t("training_data_s3_desc")}
                  errorText={errors.s3DataPath}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                <S3Selector label={t("training_data_s3")}
                  readOnly={readOnly}
                  objectsIsItemDisabled={(item) => !item.IsFolder}
                  setOutputPath={(value) => setData({ s3DataPath: value })}
                  outputPath={readOnly ? data.job_payload?.s3_data_path : data.s3DataPath} />
                </FormField>
                  {(data.job_payload?.s3_data_path || data.s3DataPath) &&
                  <FormField
                    label={t("dataset_info")}
                    description={t("dataset_info_desc_parquet")}
                    stretch={false}
                  >
                  <JsonEditor
                    readOnly={readOnly}
                    value={readOnly ? data.job_payload?.dataset_info2 : data.datasetInfo2}
                    onDelayedChange={(event) => onChange('datasetInfo2', event.detail.value)}
                  />
                </FormField>}
                <FormField
                  label={t("public_datasets")}
                  stretch={false}
                  description={t("select_public_datasets")}
                  errorText={errors.dataset}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <SelectDatasets data={data} setData={setData} readOnly={readOnly} refs={refs} />
                </FormField>
                <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                ]}>
                  <FormField
                    label={t("max_prompt_length")}
                    description={t("max_prompt_length_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.max_prompt_length : data.max_prompt_length}
                      onChange={({ detail: { value } }) => onChange('max_prompt_length', value)}
                    />
                  </FormField>
                  <FormField
                    label={t("max_response_length")}
                    description={t("max_response_length_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.max_response_length : data.max_response_length}
                      onChange={({ detail: { value } }) => onChange('max_response_length', value)}
                    />
                  </FormField>
                  </Grid>
                  <FormField
                    label={t("format_prompt")}
                    description={t("format_prompt")}
                    stretch={false}
                  >
                    <SelectFormatPromptType data={data} setData={setData} readOnly={readOnly} refs={refs}/>
                  </FormField>

              </SpaceBetween>
            </Container>
            <Container
              header={<Header variant="h2">{t("trainer_settings")}</Header>}
            >
            <SpaceBetween size="l">
            <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
                  <FormField
                    label={t("total_epochs")}
                    description={t("total_epochs_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.total_epochs : data.total_epochs}
                      onChange={({ detail: { value } }) => onChange('total_epochs', value)}
                    />
                  </FormField>
                  <FormField
                    label={t("max_steps")}
                    description={t("max_steps_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.max_steps : data.max_steps}
                      onChange={({ detail: { value } }) => onChange('max_steps', value)}
                    />
                  </FormField>
                </Grid>
                <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                label={t('save_freq')}
                description={t("save_freq_desc")}
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.save_freq : data.save_freq}
                  onChange={({ detail: { value } }) => onChange('save_freq', value)}
                />
              </FormField>
               <FormField
                label={t('val_freq')}
                description={t("val_freq_desc")}
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.val_freq : data.val_freq}
                  onChange={({ detail: { value } }) => onChange('val_freq', value)}
                />
              </FormField>
                  </Grid>
                  <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                ]}>
                  <FormField
                    label={t("global_batch_size")}
                    description={t("global_batch_size_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.global_batch_size : data.global_batch_size}
                      onChange={({ detail: { value } }) => onChange('global_batch_size', value)}
                    />
                  </FormField>
                  <FormField
                    label={t("val_temperature")}
                    description={t("val_temperature_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.val_temperature : data.val_temperature}
                      onChange={({ detail: { value } }) => onChange('val_temperature', value)}
                    />
                  </FormField>
                  </Grid>
            </SpaceBetween>

            </Container>

            <Container
              header={<Header variant="h2">{t("worker_settings")}</Header>}
            >
              <SpaceBetween size="l">
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                label={t("rollout_tp_size")}
                description={t("rollout_tp_size_desc")}
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.rollout_tensor_parallel_size : data.rollout_tensor_parallel_size}
                  onChange={({ detail: { value } }) => onChange('rollout_tensor_parallel_size', value)}
                />
              </FormField>
              <FormField
                label={t("rollout_limit_images")}
                description={t("rollout_limit_images_desc")}
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.limit_images : data.limit_images}
                  onChange={({ detail: { value } }) => onChange('limit_images', value)}
                />
              </FormField>
              </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                label={t("rollout_batch_size")}
                description={t("rollout_batch_size_desc")}
                stretch={false}
              >
                <Input readOnly={readOnly}
                  value={readOnly ? data.job_payload?.rollout_batch_size : data.rollout_batch_size}
                  onChange={({ detail: { value } }) => onChange('rollout_batch_size', value)}
                />
              </FormField>
              <FormField
                    label={t("rollout_num")}
                    description={t("rollout_num_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.rollout_num : data.rollout_num}
                      onChange={({ detail: { value } }) => onChange('rollout_num', value)}
                    />
              </FormField>
              </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                    label={t("mini_rollout_batch_size")}
                    description={t("mini_rollout_batch_size_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.mini_rollout_batch_size : data.mini_rollout_batch_size}
                      onChange={({ detail: { value } }) => onChange('mini_rollout_batch_size', value)}
                    />
              </FormField>
              <FormField
                    label={t("clip_ratio_low")}
                    description={t("clip_ratio_low_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.clip_ratio_low : data.clip_ratio_low}
                      onChange={({ detail: { value } }) => onChange('clip_ratio_low', value)}
                    />
              </FormField>
              </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
              <FormField
                    label={t("clip_ratio_high")}
                    description={t("clip_ratio_high_desc")}
                    stretch={false}
                  >
                    <Input readOnly={readOnly}
                      value={readOnly ? data.job_payload?.clip_ratio_high : data.clip_ratio_high}
                      onChange={({ detail: { value } }) => onChange('clip_ratio_high', value)}
                    />
              </FormField>     
               </Grid>
              <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
                  ]}>
                <FormField
                  label={t("offload_params")}
                  description={t("offload_params_desc")}
                  stretch={false}
                >
                  <Toggle
                    readOnly={readOnly}
                    checked={readOnly ? data.job_payload?.offload_params : data.offload_params}
                    onChange={({ detail: { checked } }) => onChange('offload_params', checked)}
                  >
                    {t("enable")}
                  </Toggle>
                </FormField>
                <FormField
                  label={t("offload_optimizer")}
                  description={t("offload_optimizer_desc")}
                  stretch={false}
                >
                  <Toggle
                    readOnly={readOnly}
                    checked={readOnly ? data.job_payload?.offload_optimizer : data.offload_optimizer}
                    onChange={({ detail: { checked } }) => onChange('offload_optimizer', checked)}
                  >
                    {t("enable")}
                  </Toggle>
                  </FormField>
              </Grid>  
              
              <FormField
                label={t('reward_score_function')}
                description={<div>{t('reward_score_function_desc')}
                <Link external href={"https://github.com/hiyouga/EasyR1/tree/main/examples/reward_function"} >{t('reference_code')}</Link>
                </div>}
                stretch={false}
              >
               <SelectRewardFunction data={data} setData={setData} readOnly={readOnly} refs={refs}/>
              </FormField>
              { (data.job_payload?.reward_function === 'customize' || data.reward_function === 'customize') &&
              <FormField 
                label={t('customize_reward_score_function')}
                description={<div>
                <Link external href={"https://github.com/hiyouga/EasyR1/blob/main/examples/reward_function/math.py"} >{t('reference_code')}</Link>
                </div>}
                stretch={false}
                >
                <PythonEditor      
                 readOnly={readOnly}
                value={readOnly ? data.job_payload?.customize_reward_function : data.customize_reward_function}
                onDelayedChange={(event) => onChange('customize_reward_function', event.detail.value)}
                /> 
              </FormField>
            }
              </SpaceBetween>
            </Container>

            <Container
              header={<Header variant="h2">{t("training_instance_settings")}</Header>}
            >
              <SpaceBetween size="l">
                <FormField
                  label={t('instance_type')}
                  description={t("select_instance_type")}
                  stretch={false}
                  errorText={errors.instance_type}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <SelectInstanceType data={data} setData={setData} readOnly={readOnly} refs={refs} />
                </FormField>
                <FormField
                  label={t('instance_amount')}
                  description={t("set_instance_amount")}
                  stretch={false}
                  errorText={errors.instance_num}
                  i18nStrings={{ errorIconAriaLabel: 'Error' }}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload.instance_num : data.instance_num}
                    ref={refs.instance_num}
                    onChange={({ detail: { value } }) => onChange('instance_num', value)}
                  />
                </FormField>
                <FormField
                  label={t("training_plan")}
                  description={t("use_training_plan")}
                  stretch={false}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload.training_plan : data.training_plan}
                    ref={refs.training_plan}
                    onChange={({ detail: { value } }) => onChange('training_plan', value)}
                  />
                </FormField>
                <FormField
                  label={t("use_spot")}
                  description={t("use_spot_desc")}
                  stretch={false}
                >
                  <Toggle
                    readOnly={readOnly}
                    checked={readOnly ? data.job_payload?.use_spot : data.use_spot}
                    onChange={({ detail: { checked } }) => onChange('use_spot', checked)}
                  >
                    {t("enable")}
                  </Toggle>
                </FormField>
                <FormField
                  label={t("max_spot_wait")}
                  description={t("max_spot_wait_desc")}
                  stretch={false}
                >
                  <Input readOnly={readOnly}
                    value={readOnly ? data.job_payload?.max_spot_wait : data.max_spot_wait}
                    onChange={({ detail: { value } }) => onChange('max_spot_wait', value)}
                  />
                </FormField>
                <SpotPriceInfo
                  instanceType={data.instance_type}
                  useSpot={data.use_spot}
                  readOnly={readOnly}
                />
              </SpaceBetween>
            </Container>
          </SpaceBetween>
      )
  }

const LFJobSetting = ({ validation,
  onChange,
  readOnly,
  data,
  errors,
  setData,
  setErrors,
  refs }) => {

  return (<SpaceBetween size="xl" direction="vertical">
    <Container
      header={<Header variant="h2">{t('training_job_settings')}</Header>}
    >
      <SpaceBetween size="l">
        <FormField
          label={t('model_name')}
          stretch={false}
          description={t("select_model")}
          errorText={errors.model_name}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectModelName data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <FormField
          label={t("use_existing_model_weight")}
          stretch={false}
          description={t("use_existing_model_weight_desc")}
          errorText={errors.s3_model_path}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <S3Selector
            readOnly={readOnly}
            objectsIsItemDisabled={(item) => !item.IsFolder}
            setOutputPath={(value) => setData({ s3_model_path: value })}
            outputPath={readOnly ? data.job_payload?.s3_model_path : data.s3_model_path} />
        </FormField>
        <FormField
          label={t("use_existing_checkpoint")}
          stretch={false}
          description={t("use_existing_checkpoint_lora_desc")}
          errorText={errors.s3_checkpoint}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <S3Selector
            readOnly={readOnly}
            objectsIsItemDisabled={(item) => !item.IsFolder}
            setOutputPath={(value) => setData({ s3_checkpoint: value })}
            outputPath={readOnly ? data.job_payload?.s3_checkpoint : data.s3_checkpoint} />
        </FormField>
        <FormField
          label={t("select_chat_template")}
          description={t("select_chat_template_desc")}
          stretch={false}
          errorText={errors.prompt_template}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectPromptTemplate data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <FormField
          label={t('finetuning_method')}
          description={t("choose_ft_method")}
          stretch={true}
        >
          <RadioGroup
            items={FT_OPTIONS}
            readOnly={readOnly}
            value={readOnly ? data.job_payload?.finetuning_method : data.finetuning_method}
            onChange={({ detail: { value } }) => onChange('finetuning_method', value)}
            ref={refs.finetuning_method}
          />
        </FormField>
        {/* <FormField
          label="Quantization bit"
          description="Enable 4/8-bit model quantization (QLoRA)."
          stretch={true}
        >
          <RadioGroup
            items={QUANT_OPTIONS}
            readOnly={readOnly}
            value={readOnly ? data.job_payload?.quantization_bit : data.quantization_bit}
            onChange={({ detail: { value } }) => onChange('quantization_bit', value)}
            ref={refs.quantization_bit}
          />
        </FormField> */}
        <FormField
          label={t("booster_option")}
          stretch={true}
        >
          <RadioGroup
            items={BOOSTER_OPTIONS}
            readOnly={readOnly}
            value={readOnly ? data.job_payload?.booster_option : data.booster_option}
            onChange={({ detail: { value } }) => onChange('booster_option', value)}
            ref={refs.booster_option}
          />
        </FormField>
        <FormField
          label={t("max_job_run_hour")}
          description={t("max_job_run_hour_desc")}
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={readOnly ? data.job_payload?.max_job_run_hour : data.max_job_run_hour}
            onChange={({ detail: { value } }) => onChange('max_job_run_hour', value)}
          />
        </FormField>
      </SpaceBetween>
    </Container>
    <Container
      header={<Header variant="h2">{t('datasets_settings')}</Header>}
    >
      <SpaceBetween size="l">
        <FormField
          label={t("training_data_s3")}
          stretch={false}
          description={t("training_data_s3_desc")}
          errorText={errors.s3DataPath}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <S3Selector label={t("training_data_s3")}
            readOnly={readOnly}
            objectsIsItemDisabled={(item) => !item.IsFolder}
            setOutputPath={(value) => setData({ s3DataPath: value })}
            outputPath={readOnly ? data.job_payload?.s3_data_path : data.s3DataPath} />
        </FormField>
        {(data.job_payload?.s3_data_path || data.s3DataPath) &&
          <FormField
            label={t("dataset_info")}
            description={t("dataset_info_desc_json")}
            stretch={false}
          >
            <JsonEditor
              readOnly={readOnly}
              value={readOnly ? data.job_payload?.dataset_info : data.datasetInfo}
              onDelayedChange={(event) => onChange('datasetInfo', event.detail.value)}
            />
          </FormField>}

        <FormField
          label={t("public_datasets")}
          stretch={false}
          description={t("select_public_datasets")}
          errorText={errors.dataset}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectDatasets data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }, { colspan: { "default": 4, xxs: 4 } },
        ]}>
          <FormField
            label={t("max_samples")}
            description={t("max_samples_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.max_samples : data.max_samples}
              onChange={({ detail: { value } }) => onChange('max_samples', value)}
            />
          </FormField>
          <FormField
            label={t("cutoff_length")}
            description={t("cutoff_length_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.cutoff_len : data.cutoff_len}
              onChange={({ detail: { value } }) => onChange('cutoff_len', value)}
            />
          </FormField>
        </Grid>
        <Grid gridDefinition={[{ colspan: { "default": 4, xxs: 4 } }]}>
          <FormField
            label={t("val_size")}
            description={t("val_size_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.val_size : data.val_size}
              onChange={({ detail: { value } }) => onChange('val_size', value)}
            />
          </FormField>
        </Grid>
      </SpaceBetween>
    </Container>
    <Container
      header={<Header variant="h2">{t("training_instance_settings")}</Header>}
      footer={<DeepSpeedConfigs data={data} onChange={onChange} readOnly={readOnly} setData={setData} />}
    >
      <SpaceBetween size="l">
        <FormField
          label={t('instance_type')}
          description={t("select_instance_type")}
          stretch={false}
          errorText={errors.instance_type}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectInstanceType data={data} setData={setData} readOnly={readOnly} refs={refs} />
        </FormField>
        <FormField
          label={t('instance_amount')}
          description={t("set_instance_amount")}
          stretch={false}
          errorText={errors.instance_num}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <Input readOnly={readOnly}
            value={readOnly ? data.job_payload.instance_num : data.instance_num}
            ref={refs.instance_num}
            onChange={({ detail: { value } }) => onChange('instance_num', value)}
          />
        </FormField>
          <FormField
              label={t("training_plan")}
              description={t("use_training_plan")}
              stretch={false}
            >
              <Input readOnly={readOnly}
                value={readOnly ? data.job_payload.training_plan : data.training_plan}
                ref={refs.training_plan}
                onChange={({ detail: { value } }) => onChange('training_plan', value)}
              />
            </FormField>
        <FormField
          label={t("use_spot")}
          description={t("use_spot_desc")}
          stretch={false}
        >
          <Toggle
            readOnly={readOnly}
            checked={readOnly ? data.job_payload?.use_spot : data.use_spot}
            onChange={({ detail: { checked } }) => onChange('use_spot', checked)}
          >
            {t("enable")}
          </Toggle>
        </FormField>
        <FormField
          label={t("max_spot_wait")}
          description={t("max_spot_wait_desc")}
          stretch={false}
        >
          <Input readOnly={readOnly}
            value={readOnly ? data.job_payload?.max_spot_wait : data.max_spot_wait}
            onChange={({ detail: { value } }) => onChange('max_spot_wait', value)}
          />
        </FormField>
        <SpotPriceInfo
          instanceType={data.instance_type}
          useSpot={data.use_spot}
          readOnly={readOnly}
        />
      </SpaceBetween>
    </Container>
    <Container header={<Header variant="h2">{t("hyper_params_settings")}</Header>}
      footer={<AdvancedConfigs data={data} onChange={onChange} readOnly={readOnly} setData={setData} />}
    >
      <SpaceBetween size="l">
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label={t("learning_rate")}
            description={t("learning_rate_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.learning_rate : data.learning_rate}
              onChange={({ detail: { value } }) => onChange('learning_rate', value)}
            />
          </FormField>
          <FormField
            label={t("epoch")}
            description={t("epoch_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.num_train_epochs : data.num_train_epochs}
              onChange={({ detail: { value } }) => onChange('num_train_epochs', value)}
            />
          </FormField>
        </Grid>
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label={t("batch_size_per_device")}
            description={t("batch_size_per_device_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.per_device_train_batch_size : data.per_device_train_batch_size}
              onChange={({ detail: { value } }) => onChange('per_device_train_batch_size', value)}
            />
          </FormField>
          <FormField
            label={t("gradient_accumulation")}
            description={t("gradient_accumulation_desc")}
            stretch={false}
          >
            <Input readOnly={readOnly}
              value={readOnly ? data.job_payload?.gradient_accumulation_steps : data.gradient_accumulation_steps}
              onChange={({ detail: { value } }) => onChange('gradient_accumulation_steps', value)}
            />
          </FormField>
        </Grid>
        <Grid gridDefinition={[{ colspan: { "default": 6, xxs: 4 } }, { colspan: { "default": 6, xxs: 4 } }]}>
          <FormField
            label={t("training_precision")}
            description={t("training_precision_desc")}
            stretch={false}
          >
            <SelectTrainingPrecision data={data} readOnly={readOnly} setData={setData} />
          </FormField>
        </Grid>
      </SpaceBetween>
    </Container>
    </SpaceBetween>
  )
}

export default function DistributionPanel({
  loadHelpPanelContent,
  validation = false,
  readOnly = false,
  data,
  errors = {},
  setData,
  setErrors,
  setNotificationData,
  setDisplayNotify,
  setReadOnly,
  refs = {},
}) {

  const onChange = (attribute, value) => {
    setData({ [attribute]: value });

    // Validates when there is an error message in the field
    if (validation && errors[attribute]?.length > 0) {
      const { errorText } = validateField(attribute, value);
      setErrors({ [attribute]: errorText });
    }
  };


  const onBlur = attribute => {
    if (!validation) {
      return;
    }

    const value = data[attribute];
    const { errorText } = validateField(attribute, value);

    setErrors({ [attribute]: errorText });
  };

  useEffect(() => {
    //遍历data.job_payload中的所有元素，并setData({ [attribute]: value })
    if (data.job_payload) {
      Object.entries(data.job_payload).forEach(([attribute, value]) => {
        setData({ [attribute]: value });
      });
      setData({
        job_name: data.job_name
      });
      setData({
        stage: data.job_type
      });
      setData({
        s3DataPath: data.job_payload.s3_data_path
      });
      setData({
        datasetInfo: data.job_payload.dataset_info
      });
      setData({
        datasetInfo2: data.job_payload.dataset_info2
      });
    }
    console.log('init data:', data);

  }, [])

  return (
    <SpaceBetween size="xl" direction="vertical">
      <Container
        header={<Header variant="h2">{t('basic_info')}</Header>}
      >
        <SpaceBetween size="l">
          <FormField
            label={t('job_name')}
            description={t("job_name_desc")}
            stretch={false}
            errorText={errors.job_name}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <Input readOnly={readOnly}
              value={data.job_name}
              onChange={({ detail: { value } }) => onChange('job_name', value)}
              placeholder={t("job_name_desc")}
              ref={refs.job_name}
              onBlur={() => onBlur('job_name')}
            />
          </FormField>

          <FormField
            label={t('train_stage')}
            description={t("train_stage_desc")}
            stretch={false}
            errorText={errors.stage}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SelectStage data={data} setData={setData} readOnly={readOnly} refs={refs} />
          </FormField>
        </SpaceBetween>
      </Container>

      {data.stage === 'grpo'|| data.stage === 'dapo' ||data.stage === 'gspo'||data.stage === 'cispo' ?
        <EasyR1JobSetting onChange={onChange} validation={validation} readOnly={readOnly} data={data} errors={errors} setData={setData} refs={refs} />
        :
        <LFJobSetting onChange={onChange} validation={validation} readOnly={readOnly} data={data} errors={errors} setData={setData} refs={refs} />
      }
    </SpaceBetween>
  );
}
