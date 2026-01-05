// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState } from 'react';
import {
  Button, Modal, Box, RadioGroup, RadioGroupProps, FormField,
  Link, Input, Alert,
  Toggle, SpaceBetween, Select, SelectProps
} from '@cloudscape-design/components';
import { remotePost, remoteGet } from '../../common/api-gateway';
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
  // { label: 'lmi-dist', value: 'lmi-dist' },
  // { label: 'trt-llm', value: 'trt-llm' },
  // { label: 'HF accelerate', value: 'scheduler' },
]

const DEPLOYMENT_TARGETS: RadioGroupProps.RadioButtonDefinition[] = [
  { label: 'SageMaker Endpoint', value: 'sagemaker' },
  { label: 'HyperPod Cluster', value: 'hyperpod' },
]

const defaultData = {
  instance_type: 'ml.g5.2xlarge',
  engine: 'auto',
  enable_lora: false,
  model_name: undefined,
  quantize: '',
  cust_repo_type: 'hf',
  cust_repo_addr: '',
  extra_params:{enable_prefix_caching:true},
  deployment_target: 'sagemaker',
  hyperpod_cluster_id: undefined,
  availableInstanceTypes: [] as string[],  // Available instance types from selected HyperPod cluster
  hyperpod_config: {
    replicas: 1,
    namespace: 'default',
    enable_autoscaling: false,
    min_replicas: 1,
    max_replicas: 10,
    enable_kv_cache: false,
    kv_cache_backend: 'tieredstorage',
    enable_intelligent_routing: false,
    routing_strategy: 'prefixaware',
    use_public_alb: false
  }
}

const ROUTING_STRATEGIES: SelectProps.Option[] = [
  { label: 'Prefix Aware', value: 'prefixaware', description: 'Route based on prompt prefix (default)' },
  { label: 'KV Aware', value: 'kvaware', description: 'Real-time KV cache tracking for maximum cache hits' },
  { label: 'Session', value: 'session', description: 'Route based on user session for multi-turn conversations' },
  { label: 'Round Robin', value: 'roundrobin', description: 'Simple round-robin distribution' },
]

const KV_CACHE_BACKENDS: SelectProps.Option[] = [
  { label: 'Tiered Storage (Recommended)', value: 'tieredstorage', description: 'Distributed tiered storage cache' },
  { label: 'Redis', value: 'redis', description: 'Redis-based distributed cache' },
]

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

  // Filter instance types based on deployment target and available types
  const availableOptions = React.useMemo(() => {
    if (data.deployment_target === 'hyperpod' && data.availableInstanceTypes?.length > 0) {
      // Only show instance types available in the selected HyperPod cluster
      return INSTANCE_TYPES.filter(opt => data.availableInstanceTypes.includes(opt.value));
    }
    return INSTANCE_TYPES;
  }, [data.deployment_target, data.availableInstanceTypes]);

  // Update selection when available options change
  React.useEffect(() => {
    if (data.deployment_target === 'hyperpod' && data.availableInstanceTypes?.length > 0) {
      const currentValue = selectOption?.value;
      if (!data.availableInstanceTypes.includes(currentValue)) {
        // Current selection is not available, auto-select first available
        const firstAvailable = availableOptions[0];
        if (firstAvailable) {
          setSelectOption(firstAvailable);
          setData((pre: any) => ({ ...pre, instance_type: firstAvailable.value }));
        }
      }
    }
  }, [data.availableInstanceTypes, data.deployment_target]);

  return (
    <Select
      selectedOption={selectOption}
      disabled={readOnly}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        setData((pre: any) => ({ ...pre, instance_type: detail.selectedOption.value }))
      }}
      options={availableOptions}
      selectedAriaLabel="Selected"
      placeholder={data.deployment_target === 'hyperpod' && availableOptions.length === 0
        ? "Select a cluster first"
        : "Select instance type"
      }
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

const InputEndpointName = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description={t("custom_endpoint_name_desc")}
        stretch={true}
      >
        <Input
          readOnly={readOnly}
          value={value}
          placeholder={t("endpoint_name_placeholder")}
          onChange={({ detail }) => {
            setValue(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,endpoint_name: detail.value }  }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}


const InputCustRepo = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('');
  const [typeValue, setTypeValue] = useState<string>('hf');
  return (
    <SpaceBetween size='xs'>
      <FormField
        description={t("custom_model_repo_desc_global")}
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
        description={t("custom_model_s3path_desc")}
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

const SetExtraSglang = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [contextLen, setContextLen] = useState<string>('');
  const [memFrac, setMemFrac] = useState<string>('');
  const [template, setTemplate] = useState<string>('');
  const [toolCallParser, setToolCallParser] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
        <FormField
        label={t("mem_fraction_static")}
        description={t("mem_fraction_static_desc")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={memFrac}
          placeholder={"0.7"}
          onChange={({ detail }) => {
            setMemFrac(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,mem_fraction_static: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label={t("max_model_len")}
        description={t("max_model_len_desc_sglang")}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={contextLen}
          onChange={({ detail }) => {
            setContextLen(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,context_length: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label={t("chat_template")}
        description={<Box><Box>{t("chat_template_desc")}</Box>
          <Link external href={"https://docs.sglang.ai/backend/openai_api_vision.html#Chat-Template"} >{t("chat_template_ref")}</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={template}
          placeholder={"qwen2-vl"}
          onChange={({ detail }) => {
            setTemplate(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,chat_template: detail.value }  }))
          }}
        />
      </FormField>
        <FormField
        label={t("tool_call_parser")}
        description={<Box><Box>{t("tool_call_parser_desc")}</Box>
          <Link external href={"https://docs.sglang.io/advanced_features/tool_parser.html"} >{t("tool_call_parser_ref")}</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={toolCallParser}
          placeholder={"qwen25"}
          onChange={({ detail }) => {
            setToolCallParser(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,tool_call_parser: detail.value }  }))
          }}
        />
      </FormField>
    </SpaceBetween>
  )
}


const SetDeploymentTarget = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  return (
    <RadioGroup
      items={DEPLOYMENT_TARGETS}
      readOnly={readOnly}
      value={data.deployment_target || 'sagemaker'}
      onChange={({ detail }) => {
        setData((pre: any) => ({ ...pre, deployment_target: detail.value }))
      }}
    />
  )
}

interface ClusterSelectorProps {
  data: any;
  setData: (value: any) => void;
  readOnly: boolean;
}

const SelectHyperPodCluster = ({ data, setData, readOnly }: ClusterSelectorProps) => {
  const [loadStatus, setLoadStatus] = useState<any>("loading");
  const [clusters, setClusters] = useState<any[]>([]);
  const [selectOption, setSelectOption] = useState<SelectProps.Option | null>(null);
  const [loadingInstanceTypes, setLoadingInstanceTypes] = useState(false);

  const handleLoadClusters = async () => {
    setLoadStatus("loading");
    try {
      const response = await remotePost({ page_size: 100, page_index: 1 }, 'list_clusters');
      const clusterList = response.clusters || [];
      // Filter only ACTIVE clusters
      const activeClusters = clusterList.filter((c: any) => c.cluster_status === 'ACTIVE');
      setClusters(activeClusters);
      setLoadStatus("finished");
    } catch (error) {
      console.log(error);
      setLoadStatus("error");
    }
  };

  const handleLoadInstanceTypes = async (clusterId: string) => {
    setLoadingInstanceTypes(true);
    try {
      const response = await remoteGet(`cluster_instance_types/${clusterId}`);
      const instanceTypes = response?.response?.body?.instance_types || [];
      setData((pre: any) => ({
        ...pre,
        availableInstanceTypes: instanceTypes,
        // Auto-select the first available instance type if current selection is invalid
        instance_type: instanceTypes.length > 0 && !instanceTypes.includes(pre.instance_type)
          ? instanceTypes[0]
          : pre.instance_type
      }));
    } catch (error) {
      console.log('Failed to load instance types:', error);
      setData((pre: any) => ({ ...pre, availableInstanceTypes: [] }));
    }
    setLoadingInstanceTypes(false);
  };

  useEffect(() => {
    if (data.deployment_target === 'hyperpod') {
      handleLoadClusters();
    }
  }, [data.deployment_target]);

  return (
    <Select
      statusType={loadStatus}
      onLoadItems={handleLoadClusters}
      disabled={readOnly || loadingInstanceTypes}
      selectedOption={selectOption}
      placeholder={loadingInstanceTypes ? "Loading instance types..." : "Select a HyperPod cluster"}
      onChange={({ detail }) => {
        setSelectOption(detail.selectedOption);
        const clusterId = detail.selectedOption?.value;
        setData((pre: any) => ({ ...pre, hyperpod_cluster_id: clusterId }));
        // Fetch available instance types for this cluster
        if (clusterId) {
          handleLoadInstanceTypes(clusterId);
        }
      }}
      options={clusters.map((cluster) => ({
        label: cluster.cluster_name,
        value: cluster.cluster_id,
        description: `EKS: ${cluster.eks_cluster_name}`
      }))}
      selectedAriaLabel="Selected"
    />
  )
}

const SetHyperPodReplicas = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('1');
  return (
    <Input
      readOnly={readOnly}
      value={value}
      type="number"
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({
          ...pre,
          hyperpod_config: { ...pre.hyperpod_config, replicas: parseInt(detail.value) || 1 }
        }))
      }}
    />
  )
}

const SetHyperPodNamespace = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value, setValue] = useState<string>('default');
  return (
    <Input
      readOnly={readOnly}
      value={value}
      placeholder="default"
      onChange={({ detail }) => {
        setValue(detail.value);
        setData((pre: any) => ({
          ...pre,
          hyperpod_config: { ...pre.hyperpod_config, namespace: detail.value || 'default' }
        }))
      }}
    />
  )
}

// HyperPod Auto-scaling Configuration
const SetHyperPodAutoscaling = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState<boolean>(false);
  const [minReplicas, setMinReplicas] = useState<string>('1');
  const [maxReplicas, setMaxReplicas] = useState<string>('10');

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, enable_autoscaling: detail.checked }
          }))
        }}
      >
        {t("enable_autoscaling") || "Enable Auto-scaling"}
      </Toggle>
      {enabled && (
        <SpaceBetween size="s" direction="horizontal">
          <FormField label={t("min_replicas") || "Min Replicas"}>
            <Input
              readOnly={readOnly}
              value={minReplicas}
              type="number"
              onChange={({ detail }) => {
                setMinReplicas(detail.value);
                setData((pre: any) => ({
                  ...pre,
                  hyperpod_config: { ...pre.hyperpod_config, min_replicas: parseInt(detail.value) || 1 }
                }))
              }}
            />
          </FormField>
          <FormField label={t("max_replicas") || "Max Replicas"}>
            <Input
              readOnly={readOnly}
              value={maxReplicas}
              type="number"
              onChange={({ detail }) => {
                setMaxReplicas(detail.value);
                setData((pre: any) => ({
                  ...pre,
                  hyperpod_config: { ...pre.hyperpod_config, max_replicas: parseInt(detail.value) || 10 }
                }))
              }}
            />
          </FormField>
        </SpaceBetween>
      )}
    </SpaceBetween>
  )
}

// HyperPod KV Cache Configuration
const SetHyperPodKVCache = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState<boolean>(false);
  const [backend, setBackend] = useState<SelectProps.Option | null>(KV_CACHE_BACKENDS[0]);

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, enable_kv_cache: detail.checked }
          }))
        }}
      >
        {t("enable_kv_cache") || "Enable KV Cache"}
      </Toggle>
      {enabled && (
        <FormField label={t("kv_cache_backend") || "KV Cache Backend"}>
          <Select
            disabled={readOnly}
            selectedOption={backend}
            onChange={({ detail }) => {
              setBackend(detail.selectedOption);
              setData((pre: any) => ({
                ...pre,
                hyperpod_config: { ...pre.hyperpod_config, kv_cache_backend: detail.selectedOption?.value || 'tieredstorage' }
              }))
            }}
            options={KV_CACHE_BACKENDS}
            selectedAriaLabel="Selected"
          />
        </FormField>
      )}
    </SpaceBetween>
  )
}

// HyperPod Intelligent Routing Configuration
const SetHyperPodIntelligentRouting = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState<boolean>(false);
  const [strategy, setStrategy] = useState<SelectProps.Option | null>(ROUTING_STRATEGIES[0]);

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, enable_intelligent_routing: detail.checked }
          }))
        }}
      >
        {t("enable_intelligent_routing") || "Enable Intelligent Routing"}
      </Toggle>
      {enabled && (
        <FormField label={t("routing_strategy") || "Routing Strategy"}>
          <Select
            disabled={readOnly}
            selectedOption={strategy}
            onChange={({ detail }) => {
              setStrategy(detail.selectedOption);
              setData((pre: any) => ({
                ...pre,
                hyperpod_config: { ...pre.hyperpod_config, routing_strategy: detail.selectedOption?.value || 'prefixaware' }
              }))
            }}
            options={ROUTING_STRATEGIES}
            selectedAriaLabel="Selected"
          />
        </FormField>
      )}
    </SpaceBetween>
  )
}

const SetHyperPodPublicALB = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [enabled, setEnabled] = useState(data.hyperpod_config?.use_public_alb || false);

  return (
    <SpaceBetween size="s">
      <Toggle
        readOnly={readOnly}
        checked={enabled}
        onChange={({ detail }) => {
          setEnabled(detail.checked);
          setData((pre: any) => ({
            ...pre,
            hyperpod_config: { ...pre.hyperpod_config, use_public_alb: detail.checked }
          }))
        }}
      >
        {t("use_public_alb") || "Use Public ALB (Internet-Facing)"}
      </Toggle>
      {enabled && (
        <Alert type="warning">
          {t("public_alb_warning") || "Warning: Enabling public ALB exposes the endpoint to the internet. Ensure proper authentication is configured."}
        </Alert>
      )}
    </SpaceBetween>
  )
}

const SetExtraParamsInput = ({ data, setData, readOnly }: SelectQuantTypeProps) => {
  const [value1, setValue1] = useState<string>('');
  const [value2, setValue2] = useState<string>('');
  const [valueMaxNumSeqs, setMaxNumSeqs] = useState<string>('');

  const [value3, setValue3] = useState<boolean>(true);
  const [value4, setValue4] = useState<boolean>(false);
  const [value5, setValue5] = useState<string>('');
  const [toolCallParser, setToolCallParser] = useState<string>('');
  const [template, setTemplate] = useState<string>('');
  return (
    <SpaceBetween size='xs'>
      <FormField
        label={t("max_model_len")}
        description={t("max_model_len_desc_vllm")}
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
        label={t("tensor_parallel_size")}
        description={t("tensor_parallel_size_desc")}
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
      {/* <FormField
        label="chat-template"
        description={<Box><Box>"对于多模态模型，需要填写此项，否则只能当作文本模型。</Box>
          <Link external href={"https://docs.sglang.ai/backend/openai_api_vision.html#Chat-Template"} >有效值参考链接</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={template}
          placeholder={"qwen2-vl"}
          onChange={({ detail }) => {
            setTemplate(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,chat_template: detail.value }  }))
          }}
        />
      </FormField> */}
        <FormField
        label={t("tool_call_parser")}
        description={<Box><Box>{t("tool_call_parser_desc")}</Box>
          <Link external href={"https://docs.vllm.ai/en/latest/features/tool_calling.html#xlam-models-xlam"} >{t("tool_call_parser_ref")}</Link></Box>}
        stretch={false}
      >
        <Input
          readOnly={readOnly}
          value={toolCallParser}
          placeholder={"hermes"}
          onChange={({ detail }) => {
            setToolCallParser(detail.value);
            setData((pre: any) => ({ ...pre, extra_params:{...pre.extra_params,tool_call_parser: detail.value }  }))
          }}
        />
      </FormField>
      <FormField
        label={t("enable_prefix_caching")}
        description={t("enable_prefix_caching_desc")}
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
        label={t("enforce_eager")}
        description={t("enforce_eager_desc")}
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
      {/* <FormField
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
      </FormField> */}
      <FormField
        label={t("max_num_seqs")}
        description={t("max_num_seqs_desc")}
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
            <Button variant="link" onClick={() => setVisible(false)}>{t("cancel")}</Button>
            <Button variant="primary" onClick={onDeloyConfirm}
              loading={loading}
              disabled={loading}
            >{t("confirm")}</Button>
          </SpaceBetween>
        </Box>
      }
      header={t("deploy_model_endpoint")}
    ><SpaceBetween size="l">
        <FormField
          label={t("deployment_target") || "Deployment Target"}
          stretch={false}
          description={t("deployment_target_desc") || "Select where to deploy the model endpoint"}
        >
          <SetDeploymentTarget data={data} setData={setData} readOnly={false} />
        </FormField>

        {data.deployment_target === 'hyperpod' && (
          <>
            <FormField
              label={t("hyperpod_cluster") || "HyperPod Cluster"}
              stretch={false}
              description={t("hyperpod_cluster_desc") || "Select an active HyperPod cluster for deployment"}
            >
              <SelectHyperPodCluster data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("namespace") || "Kubernetes Namespace"}
              stretch={false}
              description={t("namespace_desc") || "Kubernetes namespace for the deployment (default: 'default')"}
            >
              <SetHyperPodNamespace data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("replicas") || "Replicas"}
              stretch={false}
              description={t("replicas_desc") || "Number of model replicas to deploy"}
            >
              <SetHyperPodReplicas data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("autoscaling") || "Auto-scaling"}
              stretch={false}
              description={t("autoscaling_desc") || "Automatically scale replicas based on CloudWatch metrics"}
            >
              <SetHyperPodAutoscaling data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("kv_cache") || "KV Cache"}
              stretch={false}
              description={t("kv_cache_desc") || "Enable KV cache for optimized inference performance. Reduces time to first token by up to 40%."}
            >
              <SetHyperPodKVCache data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("intelligent_routing") || "Intelligent Routing"}
              stretch={false}
              description={t("intelligent_routing_desc") || "Enable intelligent routing for optimized request distribution across replicas"}
            >
              <SetHyperPodIntelligentRouting data={data} setData={setData} readOnly={false} />
            </FormField>

            <FormField
              label={t("public_alb") || "Public ALB"}
              stretch={false}
              description={t("public_alb_desc") || "Configure the load balancer to be internet-facing (allows access from outside the VPC)"}
            >
              <SetHyperPodPublicALB data={data} setData={setData} readOnly={false} />
            </FormField>
          </>
        )}

        <FormField
          label={t("model_name")}
          stretch={false}
          description={t("select_supported_model")}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectModelName data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>
        <FormField
          label={t("custom_endpoint_name")}
          stretch={false}
        >
          <InputEndpointName data={data} setData={setData} readOnly={false} />
        </FormField>
        <FormField
          label={t("custom_model_repo")}
          stretch={false}
        >
          <InputCustRepo data={data} setData={setData} readOnly={modelNameReadOnly} />
        </FormField>
        {/* S3 path is only for SageMaker deployments */}
        {data.deployment_target === 'sagemaker' && (
          <FormField
            label={t("custom_model_s3path")}
            stretch={false}
          >
            <InputS3Path data={data} setData={setData} readOnly={modelNameReadOnly} />
          </FormField>
        )}

        <FormField
          label={t("instance_type")}
          stretch={false}
          errorText={errors.instance_type}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SelectInstanceType data={data} setData={setData} readOnly={false} />
        </FormField>

        {/* Instance count is only for SageMaker deployments - HyperPod uses replicas */}
        {data.deployment_target === 'sagemaker' && (
          <FormField
            label={t("instance_qty")}
            description={t("instance_qty_desc")}
            stretch={false}
            errorText={errors.instance_count}
            i18nStrings={{ errorIconAriaLabel: 'Error' }}
          >
            <SetInstanceQty data={data} setData={setData} readOnly={false} />
          </FormField>
        )}

        <FormField
          label={t("engine_type")}
          stretch={false}
          errorText={errors.engine}
          description={<Link href='https://docs.djl.ai/docs/serving/serving/docs/lmi/user_guides/vllm_user_guide.html' external>{t("engine_support_info")}</Link>}
          i18nStrings={{ errorIconAriaLabel: 'Error' }}
        >
          <SetEngineType data={data} setData={setData} readOnly={false} />
        </FormField>

        {data.engine === 'vllm' && 
          <SetExtraParamsInput data={data} setData={setData} readOnly={false} />}

        {data.engine === 'sglang' && 
          <SetExtraSglang data={data} setData={setData} readOnly={false} />}
      </SpaceBetween>
    </Modal>
  );
}