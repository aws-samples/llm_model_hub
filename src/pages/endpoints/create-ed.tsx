// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from 'react';
import {
  Button, Modal, Box, RadioGroup, RadioGroupProps, FormField,
  Link, Input,
  Toggle, SpaceBetween, Select, SelectProps
} from '@cloudscape-design/components';
import { remotePost } from '../../common/api-gateway';
import { useSimpleNotifications } from '../commons/use-notifications';
import { useNavigate } from "react-router-dom";
import { t } from 'i18next';
import {S3Selector} from '../jobs/create-job/components/output-path';


interface PageHeaderProps {
  extraActions?: React.ReactNode;
  selectedItems: ReadonlyArray<any>,
  visible: boolean;
  setVisible: (value: boolean) => void;
  setDisplayNotify: (value: boolean) => void;
  setNotificationData: (value: any) => void;
  onDelete?: () => void;
  onRefresh?: () => void;
}

interface SelectInstanceTypeProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
  // refs?:Record<string,React.RefObject<any>>;
}
interface SelectQuantTypeProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
}
interface SelectModelProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
  // refs?:Record<string,React.RefObject<any>>;
}

const defaultErrors = {
  instance_type: null,
  engine: null,
  enable_lora: null,
  model_name: null,
  quantize: null,
  instance_count:null,
}

const HF_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "int8", value: "bitsandbytes8" },
  { label: "int4", value: "bitsandbytes4" },
]

const LMI_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "awq", value: "awq" },
  { label: "gptq", value: "gptq" },
]

const TRT_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "awq", value: "awq" },
  { label: "smoothquant", value: "smoothquant" },
]

const vLLM_QUANT_TYPES = [
  { label: "None", value: "" },
  { label: "awq", value: "awq" },
]

const INSTANCE_TYPES: SelectProps.Option[] = [
  { label: 'ml.g4dn.2xlarge', value: 'ml.g4dn.2xlarge' },
  { label: 'ml.g4dn.12xlarge', value: 'ml.g4dn.12xlarge' },
  { label: 'ml.g5.xlarge', value: 'ml.g5.xlarge' },
  { label: 'ml.g5.2xlarge', value: 'ml.g5.2xlarge' },
  { label: 'ml.g5.4xlarge', value: 'ml.g5.4xlarge' },
  { label: 'ml.g5.12xlarge', value: 'ml.g5.12xlarge' },
  { label: 'ml.g5.48xlarge', value: 'ml.g5.48xlarge' },
  { label: 'ml.g6.2xlarge', value: 'ml.g6.2xlarge' },
  { label: 'ml.g6.12xlarge', value: 'ml.g6.12xlarge' },
  { label: 'ml.g6.48xlarge', value: 'ml.g6.48xlarge' },
  { label: 'ml.g6e.2xlarge', value: 'ml.g6e.2xlarge' },
  { label: 'ml.g6e.12xlarge', value: 'ml.g6e.12xlarge' },
  { label: 'ml.g6e.48xlarge', value: 'ml.g6e.48xlarge' },
  { label: 'ml.p3.2xlarge', value: 'ml.p3.2xlarge' },
  { label: 'ml.p3.8xlarge', value: 'ml.p3.8xlarge' },
  { label: 'ml.p3.16xlarge', value: 'ml.p3.16xlarge' },
  { label: 'ml.p4d.24xlarge', value: 'ml.p4d.24xlarge' },
  { label: 'ml.p4de.24xlarge', value: 'ml.p4de.24xlarge' },
  { label: 'ml.p5.48xlarge', value: 'ml.p5.48xlarge' },
  { label: 'ml.p5e.48xlarge', value: 'ml.p5e.48xlarge' },
  { label: 'ml.p5en.48xlarge', value: 'ml.p5en.48xlarge' }
]

const ENGINE: RadioGroupProps.RadioButtonDefinition[] = [
  { label: 'Auto', value: 'auto' },
  { label: 'vllm', value: 'vllm' },
  { label: 'sglang', value: 'sglang' },
  { label: 'lmi-dist', value: 'lmi-dist' },
  { label: 'trt-llm', value: 'trt-llm' },
  { label: 'HF accelerate', value: 'scheduler' },
]

const defaultData = {
  instance_type: 'ml.g5.2xlarge',
  engine: 'auto',
  enable_lora: false,
  model_name: undefined,
  quantize: '',
  cust_repo_type: 'hf',
  cust_repo_addr: '',
  extra_params:{}
}

const instanceCalculator = process.env.REACT_APP_CALCULATOR;

const SelectModelName = ({ data, setData, readOnly }: SelectModelProps) => {
  // console.log(data)
  const [loadStatus, setLoadStatus] = useState<any>("loading");
  const [items, setItems] = useState([]);
  // const initState = data.job_payload ? { label: data.job_payload.model_name, value: data.job_payload.model_name } : {};
  const [selectOption, setSelectOption] = useState({});
  useEffect(() => {
    if (data.model_name) {
      setSelectOption({ label: data.model_name, value: data.model_name })
      setData((pre: any) => ({ ...pre, model_name: data.model_name }))
    }
  }, [data.model_name])
  const handleLoadItems = async ({
    detail: { },
  }) => {
    setLoadStatus("loading");
    try {
      const data = await remotePost({ config_name: 'model_name' }, 'get_factory_config');
      const items = data.response.body.map((it: any) => ({
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
        setData((pre: any) => ({ ...pre, model_name: detail.selectedOption.value }))
      }}
      options={items.map(({ model_name, model_path }) => ({
        label: model_name,
        value: model_path,
        tags: [model_path]
      }))}
      selectedAriaLabel="Selected"
    />
  )
}
const SelectInstanceType = ({ data, setData, readOnly }: SelectInstanceTypeProps) => {
  const [selectOption, setSelectOption] = useState<SelectProps.Option | null>(INSTANCE_TYPES[3]);
  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData((pre: any) => ({ ...pre, instance_type: detail.selectedOption.value }))
      }}
      options={INSTANCE_TYPES}
      selectedAriaLabel="Selected"
    />
  )
}

const SetEngineType = ({ data, setData, readOnly }: SelectInstanceTypeProps) => {
  const [value, setValue] = useState<string | null>(ENGINE[0].value);
  return (
    <RadioGroup
      items={ENGINE}
      readOnly={readOnly}
      value={value}
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({ ...pre, engine: detail.value }))

      }}
    />
  )
}

const SetInstanceQty = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('1');
  return (
        <Input
          readOnly={readOnly}
          value={value}
          onChange={({ detail }) => {
            setValue(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,instance_count: detail.value }  }))
          }}
        />
  )
};

const InputCustRepo = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  const [typeValue, setTypeValue] = useState<string>('hf');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description="海外区输入HuggingFace Repo地址,例如:unsloth/llama-3-8b-Instruct，中国区请输入魔搭社区地址,例如:baicai003/Llama3-Chinese_v2"
        stretch={true}
      >
        <Input
          readOnly={readOnly}
          value={value}
          placeholder='Model Repo'
          onChange={({ detail }) => {
            setValue(detail.value);
            setData((pre: any) => ({ ...pre, cust_repo_addr: detail.value }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}

const InputS3Path = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description="输入S3存储路径，例如：s3://bucket/model/"
        stretch={true}
      >
        <S3Selector 
                objectsIsItemDisabled={(item:any) => !item.IsFolder}
                setOutputPath={(value:any)=>
                   setData((pre: any) => ({ ...pre,  extra_params:{...pre.extra_params,s3_model_path: value } }))
                  } 
              outputPath={value}/>
      </FormField>
    </SpaceBetween>
  )
};

const SetExtraParamsInput = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value1, setValue1] = useState<string>('');
  const [value2, setValue2] = useState<string>('');
  const [valueMaxNumSeqs, setMaxNumSeqs] = useState<string>('');

  const [value3, setValue3] = useState<boolean>(false);
  const [value4, setValue4] = useState<boolean>(false);
  const [value5, setValue5] = useState<string>('');


  return (
    <SpaceBetween size='xs'>
      <FormField
        label="max-model-len"
        description="模型上下文最大长度，不能超过kv cache的size,默认值12288"
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={value1}
          onChange={({ detail }) => {
            setValue1(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,max_model_len: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label="tensor-parallel-size"
        description="tensor并行度,默认是实例的GPU数量"
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={value2}
          onChange={({ detail }) => {
            setValue2(detail.value);
            setData((pre: any) => ({ ...pre,  extra_params:{...pre.extra_params,tensor_paralle_size: detail.value } }))
          }}
        />
      </FormField>
      <FormField
        label="enable-prefix-caching"
        description="是否启用prefix caching"
        stretch={false}
      >
        <Toggle
          readOnly={readOnly}
          checked={value3}
          onChange={({ detail }) => {
            setValue3(detail.checked);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,enable_prefix_caching: detail.checked }  }))
          }}
        >
          {t("enable")}
        </Toggle>
      </FormField>
      <FormField
        label="enfore-eager"
        description="是否启用PyTorch eager-mode，默认False"
        stretch={false}
      >
        <Toggle
          readOnly={readOnly}
          checked={value4}
          onChange={({ detail }) => {
            setValue4(detail.checked);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,enforce_eager: detail.checked }  }))
          }}
        >
          {t("enable")}
        </Toggle>
      </FormField>
      <FormField
        label="limit-mm-per-prompt"
        description="一个请求最大支持图片或者video数量，默认是image=1，设置值格式为 image=N,video=M"
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={value5}
          placeholder='image=5,video=2'
          onChange={({ detail }) => {
            setValue5(detail.value);
            setData((pre: any) => ({ ...pre,  extra_params:{...pre.extra_params,limit_mm_per_prompt: detail.value } }))
          }}
        />
      </FormField>
      <FormField
        label="max-num-seqs"
        description="Maximum number of sequences per iteration.,默认值256"
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={valueMaxNumSeqs}
          placeholder='256'
          onChange={({ detail }) => {
            setMaxNumSeqs(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,max_num_seqs: detail.value }  }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}

const SetQuantType = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const quant_types = data?.engine === 'scheduler' ?
    HF_QUANT_TYPES : data?.engine === 'vllm' ?
      vLLM_QUANT_TYPES : data?.engine === 'trt-llm' ?
        TRT_QUANT_TYPES : LMI_QUANT_TYPES;
  const [value, setValue] = useState<string | null>(quant_types[0].value);
  return (
    <RadioGroup
      items={quant_types}
      readOnly={readOnly}
      value={value}
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({ ...pre, quantize: detail.value }))
      }}
    />
  )
}

const EnableLora = ({ data, setData, readOnly }: SelectInstanceTypeProps) => {
  const [checked, setChecked] = useState<boolean>(false);
  return (
    <Toggle
      onChange={({ detail }) => {
        setChecked(detail.checked);
        setData((pre: any) => ({ ...pre, enable_lora: detail.checked }))
      }
      }
      checked={checked}
    >
      Enable
    </Toggle>
  )

}

export const DeployModelModal = ({
  extraActions = null,
  selectedItems,
  visible,
  setVisible,
  setDisplayNotify,
  setNotificationData,
  onRefresh,
  ...props
}: PageHeaderProps) => {
  const [errors, _setErrors] = useState(defaultErrors);
  const [data, setData] = useState(defaultData);
  const [loading, setLoading] = useState(false);
  const { setNotificationItems } = useSimpleNotifications();
  const navigate = useNavigate();

  useEffect(() => {
    setData((pre: any) => ({ ...pre, model_name: selectedItems[0]?.job_payload?.model_name }));
  }, [])
  const modelNameReadOnly = selectedItems[0]?.job_payload?.model_name ? true : false;

  // console.log(selectedItems)
  const onDeloyConfirm = () => {
    setLoading(true);
    const msgid = `msg-${Math.random().toString(8)}`;
    const jobId = selectedItems[0]?.job_id ?? "N/A(Not finetuned)";
    const fromData = { ...data, job_id: jobId }
    remotePost(fromData, 'deploy_endpoint').
      then(res => {
        if (res.response.result) {
          setVisible(false);
          setLoading(false);
          setNotificationItems((item: any) => [
            ...item,
            {
              type: "success",
              content: `Create Endpoint Name:${res.response.endpoint_name}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items: any) =>
                  items.filter((item: any) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          onRefresh?.();
          navigate('/endpoints');
        } else {
          setVisible(false);
          setLoading(false);
          setNotificationItems((item: any) => [
            ...item,
            {
              type: "error",
              content: `Create Endpoint failed:${res.response.endpoint_name}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items: any) =>
                  items.filter((item: any) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          onRefresh?.();
        }

      })
      .catch(err => {
        setVisible(false);
        setNotificationItems((item: any) => [
          ...item,
          {
            type: "error",
            content: `Create Endpoint failed:${err}`,
            dismissible: true,
            dismissLabel: "Dismiss message",
            onDismiss: () =>
              setNotificationItems((items: any) =>
                items.filter((item: any) => item.id !== msgid)
              ),
            id: msgid,
          },
        ]);
        onRefresh?.();
        setLoading(false);
      })
  }
  return (
    <Modal
      onDismiss={() => setVisible(false)}
      visible={visible}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="link" onClick={() => setVisible(false)}>Cancel</Button>
            <Button variant="primary" onClick={onDeloyConfirm}
              loading={loading}
              disabled={loading}
            >Confirm</Button>
          </SpaceBetween>
        </Box>
      }
      header="Deploy model as endpoint"
    ><SpaceBetween size="l">
        <FormField
          label="Model Name"
          stretch={false}
          description="select a supported Model"
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectModelName data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>

        <FormField
          label="自定义模型仓库"
          stretch={false}
        >
          <InputCustRepo data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>
        <FormField
          label="自定义模型S3Path"
          stretch={false}
        >
          <InputS3Path data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>

        <FormField
          label="Instance Type"
          // description="Select a Instance type to deploy the model."
          description={<Link href={`${instanceCalculator}`} external>使用机型计算器估算</Link>}

          stretch={false}
          errorText={errors.instance_type}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectInstanceType data={data} setData={setData} readOnly={false} />
        </FormField>

        <FormField
          label={t("instance_qty")}
          description={t("instance_qty_desc")}
          stretch={false}
          errorText={errors.instance_count}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SetInstanceQty data={data} setData={setData} readOnly={false} />
        </FormField>

        <FormField
          label="Engine Type"
          stretch={false}
          errorText={errors.engine}
          description={<Link href='https://docs.djl.ai/docs/serving/serving/docs/lmi/user_guides/vllm_user_guide.html' external>各类引擎支持模型信息</Link>}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SetEngineType data={data} setData={setData} readOnly={false} />
        </FormField>

        {data.engine === 'vllm' && 
          <SetExtraParamsInput data={data} setData={setData} readOnly={false} />}

        {/* {data.engine !== 'auto' && <FormField
            label="Quantize"
            description="Select Quantize type to deploy the model."
            stretch={false}
            errorText={errors.quantize}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SetQuantType data={data} setData={setData} readOnly={false} />
          </FormField>} */}



        {/* <FormField
            label="Enable Lora Adapter"
            stretch={false}
            errorText={errors.enable_lora}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <EnableLora data={data} setData={setData} readOnly={false}/>
          </FormField> */}
      </SpaceBetween>
    </Modal>
  );
}